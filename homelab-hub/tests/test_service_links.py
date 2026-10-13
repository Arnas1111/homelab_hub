"""Published-port link settings, host precedence, validation and persistence."""
import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]))
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.core.preferences import Preferences
from app.core.service_links import ServiceLinks, service_link_host, service_link_router, service_link_settings


class ServiceLinkTests(unittest.TestCase):
    def test_host_validation_and_resolution(self):
        self.assertEqual(ServiceLinks(host='[2001:db8::2]').host,'2001:db8::2')
        self.assertEqual(service_link_host({'host':'docker.example'},'http://tower/graphql','proxy.example'),'docker.example')
        self.assertEqual(service_link_host({'host':''},'http://192.0.2.20:80/graphql','proxy.example'),'192.0.2.20')
        self.assertEqual(service_link_host({'host':''},'','proxy.example'),'proxy.example')
        for host in ['https://tower','tower:8080','user:password@tower','bad host','../path']:
            with self.assertRaises(ValidationError): ServiceLinks(host=host)

    def test_authenticated_settings_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'settings.db'
            def db(): return sqlite3.connect(path)
            conn=db();conn.execute('CREATE TABLE settings (key TEXT PRIMARY KEY,value TEXT)');conn.commit();conn.close()
            preferences=Preferences(db)
            def auth(request: Request):
                if request.headers.get('x-auth')!='yes': raise HTTPException(401)
            app=FastAPI();app.include_router(service_link_router(preferences,auth))
            with TestClient(app) as client:
                self.assertEqual(client.get('/api/service-link-settings').status_code,401)
                self.assertEqual(client.put('/api/service-link-settings',json={'enabled':False,'host':'docker.example'}).status_code,401)
                client.headers['x-auth']='yes'
                self.assertEqual(client.get('/api/service-link-settings').json(),{'enabled':True,'host':''})
                self.assertEqual(client.put('/api/service-link-settings',json={'enabled':False,'host':'docker.example'}).status_code,200)
                self.assertEqual(service_link_settings(Preferences(db)),{'enabled':False,'host':'docker.example'})


if __name__=='__main__':unittest.main()
