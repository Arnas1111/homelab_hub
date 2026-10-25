"""Persisted Home module choices are bounded and authenticated."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]))
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from app.core.home_layout import home_layout_router
from test_automations import MemoryPreferences


class HomeLayoutTests(unittest.TestCase):
    def test_choices_persist_with_unique_module_ids_and_auth(self):
        prefs=MemoryPreferences()
        def auth(request: Request):
            if request.headers.get('x-user') != 'owner': raise HTTPException(401)
        app=FastAPI()
        app.include_router(home_layout_router(prefs,auth))
        with TestClient(app) as client:
            path='/api/home/layout'
            self.assertEqual(client.get(path).status_code,401)
            client.headers['x-user']='owner'
            self.assertIn('services',[row['id'] for row in client.get(path).json()['modules']])
            prefs.write('home_layout',[{'id':'services','width':2}])
            self.assertEqual(client.get(path).json()['modules'][0]['width'],3)
            layout={'modules':[{'id':'zigbee','width':2},{'id':'services','width':1}]}
            self.assertEqual(client.put(path,json=layout).status_code,200)
            self.assertEqual(client.get(path).json(),layout)
            self.assertEqual(client.put(path,json={'modules':[layout['modules'][0]]*2}).status_code,422)
            self.assertEqual(client.put(path,json={'modules':[{'id':'unknown','width':2}]}).status_code,422)
            note={'modules':[{'id':'notes','width':3,'content':'Remember to inspect the hub','accent':'mint'}]}
            self.assertEqual(client.put(path,json=note).json(),note)
            self.assertEqual(client.get(path).json(),note)
            self.assertEqual(client.put(path,json={'modules':[{'id':'notes','width':4}]}).status_code,422)
            self.assertEqual(client.put(path,json={'modules':[{'id':'notes','content':'x'*2001}]}).status_code,422)


if __name__=='__main__': unittest.main()
