# setup.py
from Cython.Build import cythonize
from setuptools import Extension, find_packages, setup

setup_extensions = [
    Extension(
        'aiokcp.kcp',
        ['aiokcp/kcp.c', 'aiokcp/ikcp.c'],
        include_dirs=['aiokcp']
    )
]

setup(
    name='aiokcp',
    version='0.0.1',
    description='KCP for asyncio and socketserver, based on kcp',
    author='ryanrain2016',
    author_email='holidaylover2010@gmail.com',
    packages=find_packages(),
    install_requires=[
        'cython'
    ],
    keywords=['asyncio', 'kcp', 'socket', 'aio', 'aiokcp'],
    ext_modules=cythonize(setup_extensions, language_level = "3")
)