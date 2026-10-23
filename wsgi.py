"""Production entry point; database secrets are supplied by the host."""
import os
from app import create_app

if os.environ.get('RENDER') and not os.environ.get('SQLSERVER_CONNECTION_STRING'):
    raise RuntimeError('Set SQLSERVER_CONNECTION_STRING to a reachable hosted SQL Server before deploying.')

app = create_app()
