from setuptools import setup, find_packages

# read the contents of your README file
from pathlib import Path

this_directory = Path(__file__).parent
long_description = (
    this_directory / "ethernity_cloud_runner_py" / "README.md"
).read_text()

print(this_directory);


setup(
    name="ethernity-cloud-runner-py",
    version="0.0.14",
    url="https://github.com/ethernity-cloud/ethernity-cloud-runner-py",
    author="Ethernity Cloud Team",
    author_email="contact@ethernity.cloud",
    description="Ethernity Cloud Runner Python",
    long_description=long_description,
    long_description_content_type="text/markdown",
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
