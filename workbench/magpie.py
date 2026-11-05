"""Isolated Magpie gateway, explicit free-channel routing and local credentials."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.request

from .settings import UserFacingError

MODELSCOPE = 'https://api-inference.modelscope.cn/v1'
WEBSITE = 'https://www.modelscope.cn'
GATEWAY = 'http://127.0.0.1:3425/v1'
MODEL_PREFIX = 'sw-modelscope/'
DEFAULT = {'enabled': False, 'auto_checkin': True, 'free_only': True,
           'models': {'simple': '', 'standard': '', 'complex': ''},
           'effort': 'auto', 'max_output_tokens': 32768, 'vision': False}


def read_config(store):
    path = store.root.parent / 'magpie' / 'integration.json'
    return validate_config(json.loads(path.read_text(encoding='utf-8'))) if path.exists() else validate_config(DEFAULT)


def validate_config(value):
    if not isinstance(value, dict): raise UserFacingError('额度与路由设置格式无效。')
    result = {**DEFAULT, **{k: v for k, v in value.items() if k in DEFAULT}}
    for key in ('enabled', 'auto_checkin', 'vision'):
        if not isinstance(result[key], bool): raise UserFacingError('路由开关格式无效。')
    if result['free_only'] is not True: raise UserFacingError('当前接入仅使用免费渠道，不能自动转入付费接口。')
    models = result['models']
    if not isinstance(models, dict): raise UserFacingError('请填写三个难度档的模型。')
    result['models'] = {}
    for tier in ('simple', 'standard', 'complex'):
        model = str(models.get(tier, '')).strip()
        if len(model) > 180 or (model and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/@+-]*', model)):
            raise UserFacingError('模型 ID 格式无效。')
        if model.startswith(('sk-', 'ms-', 'http')): raise UserFacingError('模型栏不能填写密钥或接口地址。')
        result['models'][tier] = model
    if result['enabled'] and not all(result['models'].values()): raise UserFacingError('启用路由前请填写三个难度档的模型。')
    if result['effort'] not in {'auto', 'none', 'low', 'medium', 'high', 'xhigh', 'max'}: raise UserFacingError('思考强度不可用。')
    cap = result['max_output_tokens']
    if isinstance(cap, bool) or not isinstance(cap, int) or not 4096 <= cap <= 131072: raise UserFacingError('输出上限需在4096到131072之间。')
    return result


def classify_task(message, *, images=False, cad_files=False, prior_design=None):
    """Conservative local classification; no extra paid classifier request."""
    text = str(message).lower()
    complex_words = ('装配', '组装', '配合', '机械臂', '曲面', '放样', '飞机', '机构', 'assembly', 'mate', 'loft')
    if images or cad_files or any(word in text for word in complex_words) or (prior_design or {}).get('document') == 'assembly':
        return {'tier': 'complex', 'reason': '包含图片、已有零件或装配/复杂结构，需要完整规划与复核。'}
    if len(text) <= 180 and any(word in text for word in ('读取', '报告', '软件版本', '立方体', '圆柱', '版本', 'cube', 'cylinder')):
        return {'tier': 'simple', 'reason': '明确的读取或基础几何需求。'}
    return {'tier': 'standard', 'reason': '常规参数化零件或修改；未满足基础任务条件。'}


def route_profiles(store, job):
    config = read_config(store)
    if not config['enabled']: return None
    if not store.vault.has('modelscope', MODELSCOPE): raise UserFacingError('请先在“额度与路由”保存魔搭令牌。')
    route = classify_task('\n'.join(job.requests), images=bool(job.references), cad_files=bool(job.cad_inputs),
                          prior_design=(job.previous_context.get('plan') or {}).get('design'))
    review_tier = 'complex' if route['tier'] == 'complex' else 'standard'
    def profile(tier):
        return {'provider': 'custom', 'base_url': GATEWAY, 'api_style': 'chat_completions',
                'model': MODEL_PREFIX + config['models'][tier], 'key': 'magpie', 'vision': config['vision'],
                'reasoning_effort': config['effort'], 'output_limit': config['max_output_tokens'],
                'transport': 'magpie', 'free_only': True}
    executor_tier = 'standard' if route['tier'] == 'complex' else 'simple'
    planner, executor, reviewer = profile(route['tier']), profile(executor_tier), profile(review_tier)
    job._reviewer_profile = reviewer
    job.routing = {**route, 'free_only': True, 'planner': planner['model'], 'executor': executor['model'], 'reviewer': reviewer['model']}
    job.event('model_routing', '免费渠道任务分配：' + {'simple': '基础', 'standard': '常规', 'complex': '复杂'}[route['tier']], **job.routing)
    return planner, executor


class MagpieService:
    def __init__(self, store, origin):
        self.store, self.origin = store, origin
        self.home = store.root.parent / 'magpie'
        self.home.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.proc = None
        self.stop = threading.Event()
        self.bridge_key = secrets.token_urlsafe(32)
        self.web_key = secrets.token_urlsafe(32)
        self.cached = {'gateway_ready': False, 'balance': None, 'balance_state': 'not_queried',
                       'checkin': {'state': 'not_configured', 'message': '尚未添加支持签到的 Magpie 账号。'}, 'models': []}
        self.last_day = None
        self.thread = threading.Thread(target=self._scheduler, daemon=True, name='magpie-checkin')
        self.thread.start()

    def env(self):
        value = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ('API_KEY', 'ACCESS_TOKEN', 'SECRET'))}
        value.update(MAGPIE_NO_ACCOUNTS='1', XDG_CONFIG_HOME=str(self.home/'config'),
                     XDG_CACHE_HOME=str(self.home/'cache'), MAGPIE_WEB_KEY=self.web_key)
        return value

    @staticmethod
    def _json(url, *, key=None, data=None, cookie=False, timeout=25):
        headers = {'Accept': 'application/json', 'User-Agent': 'SolidWorksAI-Magpie'}
        if key: headers['Cookie' if cookie else 'Authorization'] = 'm_session_id='+key if cookie else 'Bearer '+key
        if data is not None: headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(), headers=headers)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if url.startswith('http://127.0.0.1:') else urllib.request.build_opener()
        try:
            with opener.open(request, timeout=timeout) as response:
                raw = response.read(16_000_001)
            if len(raw) > 16_000_000: raise UserFacingError('服务返回数据过大。')
            return json.loads(raw)
        except urllib.error.HTTPError as exc: raise UserFacingError('渠道请求未通过，HTTP '+str(exc.code)+'。') from None
        except (OSError, ValueError): raise UserFacingError('无法连接渠道或返回格式无效。') from None

    def executable(self):
        path = self.home/'install.json'
        if not path.exists(): return None
        info = json.loads(path.read_text(encoding='utf-8'))
        executable = Path(info['executable']).resolve()
        if not executable.is_relative_to(self.home.resolve()) or not executable.is_file(): raise UserFacingError('Magpie 安装记录不可用。')
        return executable

    def install(self):
        with self.lock:
            executable = self.executable()
            if executable: return
            release = self._json('https://api.github.com/repos/yetone/magpie/releases/latest')
            asset = next(a for a in release['assets'] if a['name'] == 'magpie-cli-windows-amd64.exe')
            with urllib.request.urlopen(asset['browser_download_url'], timeout=90) as response: raw = response.read(160_000_001)
            digest = hashlib.sha256(raw).hexdigest()
            if len(raw) > 160_000_000 or asset.get('digest') != 'sha256:'+digest: raise UserFacingError('Magpie 官方文件校验未通过。')
            folder = self.home/release['tag_name'];folder.mkdir(exist_ok=True)
            executable = folder/'magpie.exe';executable.write_bytes(raw)
            (self.home/'install.json').write_text(json.dumps({'version': release['tag_name'], 'executable': str(executable), 'sha256': digest}), encoding='utf-8')

    def cli(self, *args, timeout=45):
        executable = self.executable()
        if not executable: raise UserFacingError('请先安装并启动 Magpie。')
        result = subprocess.run([str(executable), *args], cwd=self.home, env=self.env(), capture_output=True,
                                encoding='utf-8', errors='replace', timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode: raise UserFacingError('Magpie 操作未完成，请检查本机网关状态。')
        return result.stdout

    def start(self):
        with self.lock:
            self.install()
            if self.proc and self.proc.poll() is None: return self.refresh()
            # Do not attach to a different Magpie instance or its accounts.
            import socket
            with socket.socket() as probe:
                if probe.connect_ex(('127.0.0.1', 3425)) == 0: raise UserFacingError('3425端口已被其他网关使用，请关闭原 Magpie 后再启动本工作台接入。')
            config = read_config(self.store)
            models = ','.join(sorted(set(config['models'].values())-{''})) or 'unconfigured'
            self.cli('provider', 'add', 'sw-modelscope', 'url='+self.origin+'/magpie-bridge/v1', 'key='+self.bridge_key, 'models='+models)
            self.cli('accounts', 'discovery', 'off')
            self.proc = subprocess.Popen([str(self.executable()), 'serve', '--web=127.0.0.1:3430'], cwd=self.home,
                env=self.env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            for _ in range(100):
                if self.proc.poll() is not None: raise UserFacingError('Magpie 后台启动失败。')
                try:
                    self._json(GATEWAY+'/models', timeout=1);break
                except UserFacingError: time.sleep(.1)
            else: raise UserFacingError('Magpie 后台启动超时。')
            self.cached['gateway_ready'] = True
            return self.refresh()

    def save(self, data):
        config = validate_config(data.get('config', {}))
        key = str(data.get('key', '')).strip()
        if key: self.store.vault.put('modelscope', MODELSCOPE, key)
        temporary = self.home/'integration.tmp';temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8');temporary.replace(self.home/'integration.json')
        if self.proc and self.proc.poll() is None:
            self.cli('provider', 'set', 'sw-modelscope', 'models='+(','.join(sorted(set(config['models'].values())-{''})) or 'unconfigured'))
        return self.public()

    def public(self):
        with self.lock:
            return {'config': read_config(self.store), 'installed': bool(self.executable()),
                    'key_present': self.store.vault.has('modelscope', MODELSCOPE),
                    'gateway_url': GATEWAY, 'claim_url': 'https://www.modelscope.cn/magicube/usage',
                    'claim_mode': 'official_website', **self.cached}

    def open_management(self):
        if not self.proc or self.proc.poll() is not None: raise UserFacingError('请先启动 Magpie。')
        import webbrowser
        webbrowser.open('http://127.0.0.1:3430/?k='+self.web_key)
        return self.public()

    def refresh(self):
        with self.lock:
            key = self.store.vault.get('modelscope', MODELSCOPE)
            self.cached['checked_at'] = datetime.now(timezone.utc).isoformat()
            if key:
                try:
                    body = self._json(WEBSITE+'/openapi/v1/magicubes/balance', key=key, cookie=True)
                    data = body.get('data', body.get('Data', body))
                    balance = next((data[k] for k in ('balance', 'Balance', 'available_balance', 'available') if isinstance(data, dict) and k in data), None)
                    if isinstance(balance, str): balance = float(balance)
                    if isinstance(balance, bool) or not isinstance(balance, (int, float)) or not math.isfinite(balance): raise UserFacingError('余额格式暂不能识别，请在官网核对。')
                    self.cached.update(balance=balance, balance_state='verified', balance_message='魔搭接口实际余额，单位为魔粒。')
                except (UserFacingError, ValueError) as exc:
                    self.cached.update(balance=None, balance_state='unknown', balance_message=str(exc))
                try:
                    body = self._json(MODELSCOPE+'/models', key=key)
                    self.cached['models'] = [str(item['id']) for item in body.get('data', []) if isinstance(item, dict) and isinstance(item.get('id'), str)]
                except UserFacingError: self.cached['model_list_message'] = '模型列表暂不能读取，请从魔搭模型页复制准确 ID。'
            try:
                if self.proc and self.proc.poll() is None:
                    self.cached['gateway_ready'] = True
                    quota = self._json(GATEWAY+'/magpie/quotas', timeout=8)
                    # Never publish raw provider/account objects which may contain login data.
                    cards = quota if isinstance(quota, list) else quota.get('cards', quota.get('quotas', []))
                    self.cached['magpie_quota_cards'] = len(cards) if isinstance(cards, list) else 0
            except UserFacingError: self.cached['gateway_ready'] = False
            return self.public()

    def checkin(self):
        with self.lock:
            if not self.proc or self.proc.poll() is not None: raise UserFacingError('请先启动 Magpie。')
            before = self._json(GATEWAY+'/magpie/quotas', timeout=10)
            cards = before if isinstance(before, list) else before.get('cards', before.get('quotas', []))
            if not cards:
                self.cached['checkin'] = {'state': 'not_configured', 'message': '尚无支持签到的 Magpie 账号；魔搭每日额度请在官网登录领取。'}
            else:
                output = self.cli('accounts', 'checkin', timeout=60)
                # Keep credential-safe status, never treat command exit alone as credit receipt.
                state = 'needs_attention' if any(word in output.lower() for word in ('captcha', 'failed', 'error', '验证码')) else 'requested'
                self.cached['checkin'] = {'state': state, 'message': '签到请求已完成，请依据账号实际额度核对；验证码请在供应商官网处理。', 'checked_at': datetime.now(timezone.utc).isoformat()}
            return self.refresh()

    def test_models(self):
        config = read_config(self.store)
        if not self.proc or self.proc.poll() is not None: raise UserFacingError('请先启动 Magpie。')
        models = sorted(set(config['models'].values())-{''})
        if not models: raise UserFacingError('请先填写并保存任务池模型。')
        results = []
        for model in models:
            body = {'model': MODEL_PREFIX+model, 'messages': [{'role': 'user', 'content': 'Call record_probe once with status ready. This is only a connection test.'}],
                    'max_tokens': config['max_output_tokens'], 'tools': [{'type': 'function', 'function': {'name': 'record_probe', 'description': 'Record a harmless connection probe.',
                        'parameters': {'type': 'object', 'properties': {'status': {'type': 'string', 'enum': ['ready']}}, 'required': ['status'], 'additionalProperties': False}}}]}
            if config['effort'] != 'auto': body['reasoning_effort'] = config['effort']
            try:
                started = time.monotonic();result = self._json(GATEWAY+'/chat/completions', key='magpie', data=body, timeout=600)
                calls = result['choices'][0]['message'].get('tool_calls', [])
                passed = any(c.get('function', {}).get('name') == 'record_probe' and json.loads(c['function']['arguments']) == {'status': 'ready'} for c in calls)
                results.append({'model': model, 'actual_model': result.get('model'), 'tools_verified': passed, 'seconds': time.monotonic()-started, 'usage': result.get('usage')})
            except (UserFacingError, KeyError, ValueError) as exc: results.append({'model': model, 'tools_verified': False, 'message': str(exc)})
        self.cached['model_tests'] = results
        return self.public()

    def forward(self, raw, authorization):
        if not secrets.compare_digest(authorization or '', 'Bearer '+self.bridge_key): raise UserFacingError('本机渠道桥接认证未通过。')
        config = read_config(self.store)
        body = json.loads(raw)
        if body.get('model') not in set(config['models'].values()): raise UserFacingError('模型不在本机免费任务池中。')
        if self.cached.get('balance_state') == 'verified' and self.cached.get('balance', 0) <= 0: raise UserFacingError('免费额度不足，请在官网领取后刷新余额。')
        key = self.store.vault.get('modelscope', MODELSCOPE)
        if not key: raise UserFacingError('尚未保存魔搭令牌。')
        if body.get('stream'): raise UserFacingError('当前本机桥接使用非流式请求。')
        effort = body.get('reasoning_effort') or (body.get('reasoning') or {}).get('effort')
        if config['effort'] != 'auto' and effort != config['effort']: raise UserFacingError('Magpie 未保留所选思考强度，请调整模型或网关配置后再试。')
        cap = body.get('max_tokens', body.get('max_completion_tokens'))
        if isinstance(cap, bool) or not isinstance(cap, int) or not 1 <= cap <= config['max_output_tokens']: raise UserFacingError('Magpie 未保留任务输出上限。')
        result = self._json(MODELSCOPE+'/chat/completions', key=key, data=body, timeout=600)
        audit = {'time': datetime.now(timezone.utc).isoformat(), 'sent_model': body['model'], 'sent_effort': effort,
                 'sent_max_tokens': cap, 'returned_model': result.get('model'), 'usage': result.get('usage')}
        with (self.home/'request-audit.jsonl').open('a', encoding='utf-8') as stream: stream.write(json.dumps(audit, ensure_ascii=False)+'\n')
        return result

    def _scheduler(self):
        while not self.stop.wait(30):
            try:
                config = read_config(self.store)
                if not config['enabled'] or not config['auto_checkin'] or not self.proc or self.proc.poll() is not None: continue
                day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
                record = self.home/'checkin-state.json'
                previous = json.loads(record.read_text(encoding='utf-8')) if record.exists() else {}
                if previous.get('day') == day: continue
                record.write_text(json.dumps({'day': day, 'state': 'attempted'}), encoding='utf-8')
                self.checkin()
                record.write_text(json.dumps({'day': day, **self.cached['checkin']}), encoding='utf-8')
            except Exception:
                self.cached['checkin'] = {'state': 'failed', 'message': '自动签到未完成，请查看本机渠道状态。'}

    def close(self):
        self.stop.set()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired: pass
