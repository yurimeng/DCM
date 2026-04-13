"""
DCM Node Agent Python 包
"""

from setuptools import setup, find_packages

setup(
    name="dcm-node-agent",
    version="1.0.0",
    description="DCM Node Agent - 边缘计算节点代理",
    author="DCM Team",
    packages=find_packages(),
    install_requires=[
        "requests>=2.28.0",
    ],
    entry_points={
        "console_scripts": [
            "dcm-node-agent=src.node_agent:main",
        ],
    },
    python_requires=">=3.8",
)
