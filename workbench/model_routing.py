"""Preserve requested reasoning when an endpoint cannot combine it with tools."""
from urllib.parse import urlsplit
def tool_profile(profile):
    if (profile.get('provider')=='openai' and profile.get('api_style')=='chat_completions'
        and profile.get('model')=='gpt-6.1-terra'
        and profile.get('reasoning_effort','auto') not in {'auto','none'}
        and urlsplit(profile.get('base_url','')).hostname=='api.openai.com'):
        # The actual API explicitly requires Responses for Terra function tools
        # with reasoning. Keep the selected model, key, effort and capacity.
        return {**profile,'api_style':'responses','_requested_api_style':'chat_completions'}
    return profile
