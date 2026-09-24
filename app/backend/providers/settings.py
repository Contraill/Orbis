"""Small provider-declared configuration contract. Secrets never enter its views."""
from typing import Any, Literal
import json
import os
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Setting(BaseModel):
    model_config = ConfigDict(extra='forbid')
    key: str = Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')
    label: str = Field(min_length=1, max_length=100)
    description: str = Field(default='', max_length=500)
    type: Literal['string','integer','boolean','enum','url','secret']
    required: bool = False
    default: Any = None
    sensitive: bool = False
    minimum: int | None = None
    maximum: int | None = None
    max_length: int = Field(default=2048, ge=1, le=8192)
    choices: list[str] = Field(default_factory=list, max_length=32)
    allowed_hosts: list[str] = Field(default_factory=list, max_length=16)
    allowed_schemes: list[Literal['http','https']] = Field(default_factory=lambda:['http','https'])

    @model_validator(mode='after')
    def valid_definition(self):
        if self.type == 'secret': self.sensitive = True
        if self.sensitive and self.default is not None:
            raise ValueError('Sensitive defaults must not be embedded in provider code')
        if self.type == 'enum' and not self.choices:
            raise ValueError('Enum settings need choices')
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError('Invalid setting bounds')
        if self.default is not None: check_value(self,self.default)
        return self


class SettingsView(BaseModel):
    fields: list[Setting] = Field(alias='schema')
    values: dict[str, Any]
    configured_secrets: list[str]
    schema_available: bool


def check_value(field, value):
    # Never include submitted values in exception text.
    valid = True
    if field.type == 'boolean': valid = type(value) is bool
    elif field.type == 'integer':
        valid = type(value) is int and (field.minimum is None or value >= field.minimum) and (field.maximum is None or value <= field.maximum)
    else:
        valid = isinstance(value,str) and len(value) <= field.max_length
        if valid and field.type == 'enum': valid = value in field.choices
        if valid and field.type == 'url':
            try:
                parsed=urlsplit(value)
                valid=parsed.scheme in field.allowed_schemes and bool(parsed.hostname) and not parsed.username and not parsed.password and not parsed.fragment and not any(ord(c)<33 for c in value)
                if field.allowed_hosts: valid=valid and parsed.hostname in field.allowed_hosts
                parsed.port
            except ValueError: valid=False
    if field.required and (value is None or value == ''): valid=False
    if not valid: raise ValueError(f'Invalid setting: {field.key}')
    return value


def definitions(provider):
    fields=[Setting.model_validate(v) for v in getattr(provider,'settings_schema',())]
    if len(fields)>32 or len({f.key for f in fields})!=len(fields):
        raise ValueError('Settings schema must contain at most 32 unique keys')
    return fields


def runtime_settings(provider):
    """Server-side only; resolves current stored configuration on every operation."""
    from providers.live import get_settings, provider_dir
    values=get_settings(provider.id) if provider_dir(provider.id).exists() else {}
    result={}
    for field in definitions(provider):
        value=values.get(field.key,field.default)
        if value is None and not field.required: continue
        result[field.key]=check_value(field,value)
    return result


def settings_view(provider_id):
    from providers.registry import get_provider
    from providers.live import get_settings, provider_dir, LiveProviderNotFound
    provider=get_provider(provider_id)
    directory=provider_dir(provider_id)
    if not provider and not directory.exists(): raise LiveProviderNotFound('Provider not found')
    fields=definitions(provider)
    stored=get_settings(provider_id) if directory.exists() else {}
    # Once stored as sensitive, code rollback cannot accidentally declassify it.
    sensitive=_sensitive_keys(directory)
    fields=[f.model_copy(update={'sensitive':True,'default':None}) if f.key in sensitive else f for f in fields]
    return {'schema':[f.model_dump() for f in fields],
            'values':{f.key:stored.get(f.key,f.default) for f in fields if not f.sensitive},
            'configured_secrets':[f.key for f in fields if f.sensitive and bool(stored.get(f.key))],
            'schema_available':provider is not None}


def _sensitive_keys(directory):
    from providers.live import LiveProviderError
    path=directory/'settings-sensitive.json'
    if not path.exists(): return set()
    try:
        keys=json.loads(path.read_text())
        if not isinstance(keys,list) or not all(isinstance(k,str) for k in keys): raise ValueError()
        return set(keys)
    except (ValueError,OSError): raise LiveProviderError('Sensitive settings metadata is invalid') from None


def update_settings(provider_id, changes):
    from providers.registry import get_provider, registry_lock
    from providers.live import get_settings, save_settings, provider_dir, LiveProviderError, create_factory_override
    with registry_lock():
        provider=get_provider(provider_id)
        if provider is None: raise LiveProviderError('Activate a validated provider before configuring settings')
        fields=definitions(provider)
        allowed={f.key for f in fields}
        if changes.keys()-allowed: raise LiveProviderError('Unknown setting keys')
        # A factory settings directory uses the existing override lifecycle.
        if not provider_dir(provider_id).exists(): create_factory_override(provider_id)
        stored=get_settings(provider_id)
        sensitive=_sensitive_keys(provider_dir(provider_id)) | {f.key for f in fields if f.sensitive}
        proposed=dict(stored)
        for key,value in changes.items():
            if value is None: proposed.pop(key,None)
            else: proposed[key]=value
        try:
            for field in fields:
                value=proposed.get(field.key,field.default)
                if value is None and not field.required: continue
                check_value(field,value)
        except ValueError as exc: raise LiveProviderError(str(exc)) from None
        # Omitted = keep; null = clear/reset. Never round-trip a secret sentinel.
        for key,value in changes.items():
            if value is None: stored.pop(key,None)
            else: stored[key]=value
        # Persist classification before values; failures never expose a new secret.
        directory=provider_dir(provider_id)
        temporary=directory/'.settings-sensitive.tmp'
        with open(temporary,'w',opener=lambda p,flags:os.open(p,flags,0o600)) as output:
            os.chmod(temporary,0o600)
            output.write(json.dumps(sorted(sensitive))+'\n')
        os.replace(temporary,directory/'settings-sensitive.json')
        save_settings(provider_id,stored)
        return settings_view(provider_id)
