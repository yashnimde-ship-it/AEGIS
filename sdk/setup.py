from setuptools import setup, find_packages

setup(
    name="aegis-sentinel-sdk",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[],   # zero dependencies — uses stdlib only
    python_requires=">=3.10",
)
