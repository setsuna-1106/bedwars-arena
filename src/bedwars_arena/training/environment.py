"""Training environment identity used when loading a reproducible checkpoint."""
import platform
import numpy as np

REQUIRED_NUMPY_VERSION='2.3.5'


def require_training_dependency():
    if np.__version__!=REQUIRED_NUMPY_VERSION:
        raise ValueError(f'PPO requires NumPy {REQUIRED_NUMPY_VERSION}; found {np.__version__}')


def training_environment():
    config=getattr(np.__config__,'CONFIG',{}) or {}
    blas=config.get('Build Dependencies',{}).get('blas',{})
    return {'numpy_version':np.__version__,'system':platform.system(),'release':platform.release(),
            'machine':platform.machine(),'blas_name':str(blas.get('name','unknown')),
            'blas_version':str(blas.get('version','unknown'))}
