from setuptools import find_packages, setup


setup(
    name="electricity-usage-monitor",
    version="0.1.0",
    description="Electricity usage and time-of-use bill projection tools.",
    package_dir={"": "src"},
    packages=find_packages("src"),
    python_requires=">=3.9",
    install_requires=[],
    extras_require={
        "browser": ["playwright>=1.45"],
    },
    entry_points={
        "console_scripts": [
            "electricity-monitor=electricity_monitor.cli:main",
        ],
    },
)
