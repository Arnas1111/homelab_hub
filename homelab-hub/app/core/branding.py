"""Bounded raster uploads, stored outside the application image."""
import hashlib
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response


def branding_router(preferences, require_auth, static_directory):
    router = APIRouter()

    @router.get('/branding/{kind}')
    def image(kind: Literal['logo', 'favicon']):
        saved = preferences.read('branding_' + kind)
        if not saved:
            return FileResponse(static_directory / 'favicon.svg', media_type='image/svg+xml')
        import base64
        return Response(base64.b64decode(saved['data']), media_type=saved['mime'],
                        headers={'Cache-Control': 'no-cache', 'X-Content-Type-Options': 'nosniff'})

    @router.get('/api/branding', dependencies=[Depends(require_auth)])
    def get():
        return {kind: (preferences.read('branding_' + kind) or {}).get('revision', '') for kind in ('logo', 'favicon')}

    @router.put('/api/branding/{kind}', dependencies=[Depends(require_auth)])
    async def upload(kind: Literal['logo', 'favicon'], request: Request):
        import base64
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 512 * 1024:
                raise HTTPException(413, 'Image must be at most 512 KB')
        mime = None
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            mime = 'image/png'
        elif data.startswith(b'\xff\xd8\xff'):
            mime = 'image/jpeg'
        elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            mime = 'image/webp'
        if not mime:
            raise HTTPException(422, 'Choose a PNG, JPEG or WebP image')
        revision = hashlib.sha256(data).hexdigest()[:16]
        preferences.write('branding_' + kind, {'data': base64.b64encode(data).decode(), 'mime': mime, 'revision': revision})
        return {'revision': revision}

    @router.delete('/api/branding/{kind}', dependencies=[Depends(require_auth)])
    def reset(kind: Literal['logo', 'favicon']):
        preferences.write('branding_' + kind, None)
        return {'revision': ''}

    return router
