"""Opt-in real planner check: underspecified engineering request must not write CAD."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    from workbench.settings import SettingsStore,ARTIFACT_ROOT
    from workbench.engine import WorkbenchEngine
    from workbench.jobs import JobManager
    manager=JobManager(WorkbenchEngine(SettingsStore()),ARTIFACT_ROOT)
    job=manager.submit('帮我做一个电机支架。');deadline=time.monotonic()+180
    while manager.active and time.monotonic()<deadline:time.sleep(.5)
    assert not manager.active,'Planner still active'
    state=manager.get(job['id']);folder=Path(state['output_dir'])
    task=json.loads((folder/'task.json').read_text(encoding='utf-8'))
    assert state['phase']=='clarify',state['summary']
    assert task['tool_results'] and all(t['tool'] in {'solidworks_connect','solidworks_health_check'} for t in task['tool_results'])
    assert not list(folder.rglob('*.SLDPRT')) and not list(folder.rglob('*.SLDASM'))
    print(json.dumps({'status':'passed','job_id':job['id'],'questions':state['summary'],'cad_write':False},ensure_ascii=False))
    manager.pool.shutdown()


if __name__=='__main__':main()
