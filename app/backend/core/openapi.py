"""Publish the additive V1 error contract for all frontend-facing HTTP routes."""
from fastapi.openapi.utils import get_openapi


def install(app):
    def schema():
        if app.openapi_schema: return app.openapi_schema
        result=get_openapi(title=app.title,version=app.version,routes=app.routes)
        result.setdefault('components',{}).setdefault('schemas',{})['ErrorV1']={
            'type':'object','required':['detail','error'],'properties':{
                'detail':{'description':'Compatibility field; new clients use error.code.'},
                'error':{'type':'object','required':['code','message','details'],'properties':{
                    'code':{'type':'string'},'message':{'type':'string'},'details':{}}}}}
        for path in result['paths'].values():
            for operation in path.values():
                if not isinstance(operation,dict) or 'responses' not in operation: continue
                for status in ('400','401','403','404','409','410','422','429','500','502','503'):
                    operation['responses'][status]={'description':'Normalized V1 error','content':{'application/json':{'schema':{'$ref':'#/components/schemas/ErrorV1'}}}}
        app.openapi_schema=result
        return result
    app.openapi=schema
