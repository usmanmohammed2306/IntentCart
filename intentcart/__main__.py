import os
import uvicorn

if __name__ == '__main__':
    if os.getenv('INTENTCART_MANAGED_INSTALL')=='true':
        from .installation import prepare
        prepare()
    uvicorn.run('intentcart.app:app', host=os.getenv('HOST', '127.0.0.1'), port=int(os.getenv('PORT', '4000')), workers=1)
