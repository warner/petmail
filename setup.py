
from setuptools import setup
import versioneer

commands = versioneer.get_cmdclass()

setup(name="petmail",
      version=versioneer.get_version(),
      description="Secure messaging and files",
      author="Brian Warner",
      author_email="warner-petmail@lothar.com",
      license="MIT",
      url="https://github.com/warner/petmail",
      packages=["petmail", "petmail.mailbox",
                "petmail.scripts", "petmail.test"],
      entry_points={
          'console_scripts': [ 'petmail = petmail.scripts.runner:entry' ],
          },
      install_requires=["Twisted >= 13.1.0", "PyNaCl >= 0.2.3",
                        "magic-wormhole == 0.4.0"],
      cmdclass=commands,
      )
