from pathlib import Path

from setuptools import setup, find_packages

# The PyPI page is the repository README.
long_description = (Path(__file__).parent / "README.md").read_text(encoding="utf-8")


setup(
    name="ethernity-cloud-runner-py",
    version="0.5.17",
    url="https://github.com/ethernity-cloud/ethernity-cloud-runner-py",
    author="Ethernity Cloud Team",
    author_email="contact@ethernity.cloud",
    description="Ethernity Cloud Runner Python",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages("."),
    install_requires=[
        "web3==7.6.0",
        "eth-typing",
        "python-dotenv",
        "tinyec",
        "cryptography",
        "requests",
        "pyasn1",
        "pynacl",
        "ckzg==2.0.1"
    ],
)
