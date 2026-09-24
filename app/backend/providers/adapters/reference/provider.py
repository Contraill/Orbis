"""Offline reference adapter. Run the synthetic fixture service described in docs.

Only metadata calls reach a loopback fixture endpoint. The reserved media origin
is intercepted by the test harness; production relay SSRF checks are unchanged.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
import httpx
import json
from providers.contract import MediaProvider, ProviderUnavailable
from providers.settings import Setting, runtime_settings
from providers.schemas import PlaybackSource, ProviderCapabilities, ProviderHealthResult, ProviderSearchResult


class ReferenceProvider(MediaProvider):
    id = 'reference'
    name = 'Local fixture reference (authoring example)'
    default_enabled = False
    default_priority = 500
    capabilities = ProviderCapabilities(movie=True,episode=True,protocols=['hls','http'])
    settings_schema = (
        Setting(key='endpoint',label='Fixture endpoint',type='url',required=True,default='http://127.0.0.1:8765',allowed_hosts=['127.0.0.1','::1'],allowed_schemes=['http'],description='Loopback synthetic fixture service only; no external streaming site.'),
        Setting(key='include_backup',label='Include backup source',type='boolean',default=True),
        Setting(key='scenario',label='Fixture scenario',type='enum',choices=['normal','primary_unavailable'],default='normal'),
        Setting(key='label',label='Source label prefix',type='string',default='Synthetic',max_length=40),
        Setting(key='ttl_seconds',label='Source lifetime',type='integer',default=600,minimum=60,maximum=3600),
        Setting(key='fixture_token',label='Synthetic fixture token',type='secret',description='Optional test value; never use a real credential.'),
    )

    async def _catalog(self):
        try:
            config=runtime_settings(self)
            endpoint=config['endpoint'].rstrip('/')
            parsed=urlsplit(endpoint)
            # Exact loopback literal: no hostnames, redirects or DNS rebinding.
            if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','::1') or parsed.path not in ('','/') or parsed.query:
                raise ProviderUnavailable('Reference endpoint must be an HTTP loopback fixture')
            async with httpx.AsyncClient(timeout=3,follow_redirects=False,trust_env=False) as client:
                async with client.stream('GET',endpoint+'/catalog.json',headers={'X-Fixture-Token':config.get('fixture_token','')}) as response:
                    if response.status_code!=200: raise ValueError('fixture response')
                    body=bytearray()
                    async for chunk in response.aiter_bytes(8192):
                        body.extend(chunk)
                        if len(body)>65536: raise ValueError('fixture response')
                    data=json.loads(body)
                    if not isinstance(data,list) or len(data)>20: raise ValueError('fixture catalog')
            return config,data
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderUnavailable('Synthetic fixture unavailable or configuration invalid') from None

    async def health_check(self):
        await self._catalog()
        return ProviderHealthResult(healthy=True,message='Synthetic fixture reachable')

    async def search(self, query):
        _,entries=await self._catalog()
        return [ProviderSearchResult(provider_id=self.id,external_id=e['key'],title=e['title'])
                for e in entries if query.casefold() in e['title'].casefold()]

    async def _resolve(self, key):
        config,entries=await self._catalog()
        entry=next((e for e in entries if e['key']==key),None)
        if not entry: raise ProviderUnavailable('Canonical title is not mapped in synthetic catalog')
        expiry=datetime.now(timezone.utc)+timedelta(seconds=config['ttl_seconds'])
        result=[]
        for item in entry['sources']:
            if item['id']=='primary' and config['scenario']=='primary_unavailable': continue
            if item['id']=='backup' and not config['include_backup']: continue
            # Fixture data never becomes arbitrary URLs or caller-supplied headers.
            if item['id'] not in ('primary','backup'): continue
            path='master.m3u8' if item['id']=='primary' else 'sample.mp4'
            result.append(PlaybackSource(provider_id=self.id,source_id=item['id'],
                source_label=f"{config['label']} {item['id']}",url=f'https://media.orbis.example/{path}',
                protocol='hls' if item['id']=='primary' else 'http',
                quality=None if item['id']=='primary' else '360p',
                headers={'X-Fixture-Token':config['fixture_token']} if config.get('fixture_token') else {},
                expires_at=expiry))
        if not result: raise ProviderUnavailable('No synthetic source available in this scenario')
        return result

    async def resolve_movie(self, tmdb_id):
        return await self._resolve(f'movie:{tmdb_id}')

    async def resolve_episode(self, tmdb_id, season, episode):
        return await self._resolve(f'tv:{tmdb_id}:s{season}:e{episode}')


PROVIDER = ReferenceProvider()
