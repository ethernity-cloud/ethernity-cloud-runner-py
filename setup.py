from setuptools import setup, find_packages

setup(
    name="ethernity-cloud-runner-py",
    version="0.0.9",
    url="https://github.com/ethernity-cloud/ethernity-cloud-runner-py",
    author="Ethernity Cloud Team",
    author_email="alexlga@gmail.com",
    description="Ethernity Cloud Runner Python SDK",
    packages=find_packages("."),
    install_requires=[
        "web3==6.19.0",
        "eth-typing==4.3.0",
        "ipfshttpclient",
        "python-dotenv",
        "tinyec",
        "cryptography",
        "requests",
        "pyasn1",
        "pynacl",
        "coincurve",
    ],
)
