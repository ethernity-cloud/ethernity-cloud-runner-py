from setuptools import setup, find_packages

setup(
    name="ethernity-cloud-runner-py",
    version="0.0.1",
    url="https://github.com/ethernity-cloud/ethernity-cloud-runner-py",
    author="Author Name",
    author_email="author@gmail.com",
    description="Description of my package",
    packages=find_packages(),
    install_requires=[
        "web3",
        "ipfshttpclient",
        "python-dotenv",
        "tinyec",
        "cryptography",
    ],
)
