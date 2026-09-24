import asyncio
import json
import stat
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
import httpx
from test_playback_hardening import HardeningTestCase
from core.auth import require_owner
from main import app
import providers.live as live
import providers.registry as registry
from providers.settings import settings_view,update_settings,runtime_settings,Setting
from providers.contract import ProviderUnavailable
from providers.manager import ProviderManager
from playback.choices import manifest_qualities
from playback.delivery import DeliveryBroker
from playback.source_sessions import source_sessions
from db.models.provider import ProviderState

FIXTURES=Path(__file__).parent/'provider_fixtures/reference'


class ProviderReadinessTests(HardeningTestCase):
    def setUp(self):
        super().setUp()
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.addCleanup(registry.reload_registry)
        for module in (live,registry):
            p=patch.object(module,'LIVE_PROVIDER_ROOT',self.root);p.start();self.addCleanup(p.stop)
        registry.reload_registry()
        app.dependency_overrides[require_owner]=lambda:self.profile

    def install(self, provider_id='local-reference'):
        code=registry.factory_code('reference').replace("id = 'reference'",f"id = '{provider_id}'")
        live.create_live_provider(provider_id,'Local reference')
        live.save_draft(provider_id,code)
        self.assertTrue(live.validate_draft(provider_id)['valid'])
        live.activate_draft(provider_id)
        return provider_id

    def test_fresh_production_discovery_excludes_tests_and_reference_is_opt_in(self):
        providers=registry.all_providers()
        self.assertIn('reference',providers)
        self.assertFalse({'mock-stream','mock-broken'} & set(providers))
        self.assertFalse(providers['reference'].default_enabled)
        self.assertIsNone(registry.factory_code('mock-stream'))
        self.assertIsNone(registry.factory_code('mock-broken'))
        views=ProviderManager().list_providers(self.db)
        self.assertEqual({v.provider_id for v in views},set(providers))

    def test_settings_mask_patch_clear_constraints_and_permissions(self):
        provider_id=self.install()
        path=f'/api/admin/provider-editor/{provider_id}/settings'
        response=self.client.put(path,json={'settings':{'fixture_token':'synthetic-sensitive-value','ttl_seconds':120,'include_backup':False}})
        self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn('synthetic-sensitive-value',response.text)
        self.assertEqual(response.json()['configured_secrets'],['fixture_token'])
        self.assertNotIn('synthetic-sensitive-value',self.client.get(path).text)
        self.assertEqual(runtime_settings(registry.get_provider(provider_id))['fixture_token'],'synthetic-sensitive-value')
        self.assertEqual(stat.S_IMODE((self.root/provider_id/'settings.json').stat().st_mode),0o600)
        response=self.client.put(path,json={'settings':{'label':'Changed'}})
        self.assertEqual(response.json()['configured_secrets'],['fixture_token'])
        for invalid in ({'ttl_seconds':True},{'ttl_seconds':1},{'scenario':'invalid'},{'endpoint':'https://user:private@host.test'},{'unknown':'private'}):
            result=self.client.put(path,json={'settings':invalid})
            self.assertEqual(result.status_code,400,result.text)
            self.assertNotIn('private',result.text)
        self.assertEqual(self.client.put(path,json={'settings':{'fixture_token':None}}).json()['configured_secrets'],[])
        self.assertNotIn('fixture_token',runtime_settings(registry.get_provider(provider_id)))

    def test_settings_survive_versions_rollback_and_factory_revert(self):
        provider_id=self.install()
        update_settings(provider_id,{'fixture_token':'kept-secret','label':'Kept label'})
        first=live.provider_editor_state(provider_id)['active_code']
        live.save_draft(provider_id,first.replace("default_priority = 500","default_priority = 501"))
        live.activate_draft(provider_id)
        live.rollback_provider(provider_id,live.list_versions(provider_id)[0])
        self.assertEqual(runtime_settings(registry.get_provider(provider_id))['fixture_token'],'kept-secret')
        self.assertEqual(settings_view(provider_id)['values']['label'],'Kept label')
        update_settings('reference',{'fixture_token':'factory-secret'})
        live.activate_draft('reference')
        live.revert_to_factory('reference')
        self.assertEqual(runtime_settings(registry.get_provider('reference'))['fixture_token'],'factory-secret')
        self.assertNotIn('factory-secret',json.dumps(settings_view('reference')))
        with self.assertRaises(live.LiveProviderConflict):live.delete_live_provider('reference')

    def test_empty_and_inactive_schema_and_owner_boundary(self):
        live.create_live_provider('no-config','No settings')
        live.activate_draft('no-config')
        self.assertEqual(settings_view('no-config')['schema'],[])
        self.assertEqual(settings_view('no-config')['values'],{})
        live.create_live_provider('draft-only','Draft')
        self.assertFalse(settings_view('draft-only')['schema_available'])
        with self.assertRaises(live.LiveProviderError):update_settings('draft-only',{})
        app.dependency_overrides.pop(require_owner)
        self.assertEqual(self.client.get('/api/admin/provider-editor/no-config/settings').status_code,401)

    def test_schema_validation_blocks_bad_activation(self):
        live.create_live_provider('bad-schema','Bad')
        code=live.template_code('bad-schema','Bad')+'\nPROVIDER.settings_schema = [{"key":"token","label":"Token","type":"secret","default":"DO-NOT-EMBED"}]\n'
        live.save_draft('bad-schema',code)
        self.assertFalse(live.validate_draft('bad-schema')['valid'])
        with self.assertRaises(live.LiveProviderValidationError):live.activate_draft('bad-schema')

    def test_secret_classification_survives_schema_downgrade(self):
        provider_id=self.install()
        update_settings(provider_id,{'fixture_token':'keep-classified'})
        code=live.provider_editor_state(provider_id)['active_code'].replace("type='secret'","type='string'")
        live.save_draft(provider_id,code)
        live.activate_draft(provider_id)
        view=settings_view(provider_id)
        self.assertNotIn('keep-classified',json.dumps(view))
        self.assertIn('fixture_token',view['configured_secrets'])

    def test_reference_contract_fixture_transport_variants_and_fallback(self):
        provider=registry.get_provider('reference')
        requested=[]
        real_client=httpx.AsyncClient
        def transport(request):
            requested.append(request)
            self.assertEqual(request.url.host,'127.0.0.1')
            return httpx.Response(200,json=json.loads((FIXTURES/'catalog.json').read_text()))
        def client(**kwargs):return real_client(transport=httpx.MockTransport(transport),**kwargs)
        with patch('providers.adapters.reference.provider.httpx.AsyncClient',side_effect=client):
            self.assertTrue(asyncio.run(provider.health_check()).healthy)
            self.assertTrue(asyncio.run(provider.search('synthetic')))
            update_settings('reference',{'fixture_token':'synthetic-secret'})
            sources=asyncio.run(provider.resolve_movie(157336))
            self.assertEqual([s.source_id for s in sources],['primary','backup'])
            self.assertEqual(sources[0].headers,{'X-Fixture-Token':'synthetic-secret'})
            self.assertIsNotNone(sources[0].expires_at)
            self.assertEqual([q.height for q in manifest_qualities((FIXTURES/'master.m3u8').read_text())],[720,360])
            self.assertEqual(len(asyncio.run(provider.resolve_episode(1396,1,1))),2)
            with self.assertRaises(ProviderUnavailable):asyncio.run(provider.resolve_episode(1396,9,99))
            update_settings('reference',{'scenario':'primary_unavailable'})
            self.assertEqual([s.source_id for s in asyncio.run(provider.resolve_movie(157336))],['backup'])
            update_settings('reference',{'include_backup':False})
            with self.assertRaises(ProviderUnavailable):asyncio.run(provider.resolve_movie(157336))
            count=len(requested)
            with self.assertRaises(live.LiveProviderError):update_settings('reference',{'endpoint':'https://external.example'})
            self.assertEqual(len(requested),count)

    def test_delete_removes_runtime_state_without_deleting_profile_history(self):
        from playback.service import upsert_playback_state,movie_identity
        from playback.schemas import PlaybackStateUpdate
        from db.models.foundation import ViewingProgress
        from db.models.playback import PlaybackState
        from sqlalchemy import select,func
        from test_playback_hardening import SequencedProvider,source
        provider_id=self.install()
        update_settings(provider_id,{'fixture_token':'private'})
        self.db.add(ProviderState(provider_id=provider_id));self.db.commit()
        upsert_playback_state(self.db,self.profile.id,movie_identity(42),PlaybackStateUpdate(
            position_seconds=120,preferred_provider_id=provider_id),record_activity=True)
        response=self.client.delete(f'/api/admin/provider-editor/{provider_id}')
        self.assertEqual(response.status_code,204,response.text)
        self.assertFalse((self.root/provider_id).exists())
        self.assertIsNone(registry.get_provider(provider_id))
        self.assertNotIn(f'_media_app_live_{provider_id}',sys.modules)
        self.db.expire_all()
        self.assertIsNone(self.db.get(ProviderState,provider_id))
        self.assertIsNotNone(self.db.get(type(self.profile),self.profile.id))
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ViewingProgress)),1)
        self.assertEqual(self.db.scalar(select(PlaybackState)).preferred_provider_id,provider_id)
        fallback=SequencedProvider('remaining',1,[[source('remaining','fixture',protocol='http')]])
        all_patch,get_patch=self.provider_patches([fallback])
        with all_patch,get_patch:
            resolved=asyncio.run(ProviderManager().resolve_movie(self.db,42,preferred_provider_id=provider_id))
        self.assertEqual(resolved.selected_provider_id,'remaining')
