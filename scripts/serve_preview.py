"""Serve the built React application and full live API from one local origin."""
import argparse
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from backend.main import app, ROOT

DIST=ROOT/'frontend/dist'
if not (DIST/'index.html').exists():
    raise RuntimeError('Build the frontend first: cd frontend && npm run build')
app.mount('/assets',StaticFiles(directory=DIST/'assets'),name='assets')


@app.get('/{path:path}',include_in_schema=False)
def frontend(path:str):
    if path.startswith(('api/','docs/','openapi')):
        raise HTTPException(404,'Not found')
    if path=='favicon.svg':
        return FileResponse(DIST/'favicon.svg')
    return FileResponse(DIST/'index.html',headers={'Cache-Control':'no-cache'})


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=5173)
    args=parser.parse_args()
    uvicorn.run(app,host='127.0.0.1',port=args.port,workers=1)
