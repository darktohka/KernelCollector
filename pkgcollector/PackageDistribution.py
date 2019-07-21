from deb_pkg_tools.control import unparse_control_fields
from datetime import datetime
from . import Utils
import gnupg
import gzip, os

gpg = gnupg.GPG()
gpg.encoding = 'utf-8'

class PackageDistribution(object):

    def __init__(self, name, architectures, description, verbose=True):
        self.name = name
        self.architectures = architectures
        self.description = description
        self.verbose = verbose

    def getName(self):
        return self.name

    def setName(self, name):
        self.name = name

    def getArchitectures(self):
        return self.architectures

    def setArchitectures(self, architectures):
        self.architectures = architectures

    def getDescription(self):
        return self.description

    def setDescription(self, description):
        self.description = description

    def getPackageList(self):
        return self.pkgList

    def setPackageList(self, pkgList):
        self.pkgList = pkgList

        if not self.pkgList:
            return

        self.folder = os.path.join(self.pkgList.distFolder, self.name)

        if not os.path.exists(self.folder):
            os.makedirs(self.folder)

    def getArchDir(self, arch):
        return os.path.join(self.folder, 'main', 'binary-{0}'.format(arch))

    def log(self, message):
        if self.verbose:
            print(message)

    def save(self, releases):
        mainDir = os.path.join(self.folder, 'main')
        archToPackages = {arch: [] for arch in self.architectures}

        self.log("Writing package list to disk...")

        # Associate our packages with architectures.
        for release in releases:
            fullPath, data = release
            arch = data['Architecture'].lower()
            data = unparse_control_fields(data).dump()

            if arch == 'all':
                for arch in self.architectures:
                    archToPackages[arch].append(data)
            elif arch in self.architectures:
                archToPackages[arch].append(data)

        # Write our package lists for all architectures.
        for arch in self.architectures:
            archDir = self.getArchDir(arch)

            if not os.path.exists(archDir):
                os.makedirs(archDir)

            with open(os.path.join(archDir, 'Release'), 'w') as file:
                file.write('\n'.join([
                    'Component: main', 'Origin: linux-kernel', 'Label: linux-kernel',
                    'Architecture: {0}'.format(arch), 'Description: {0}'.format(self.description)
                ]))

            packages = '\n'.join(archToPackages[arch])

            with open(os.path.join(archDir, 'Packages'), 'w') as file:
                file.write(packages)

            with gzip.open(os.path.join(archDir, 'Packages.gz'), 'wt') as file:
                file.write(packages)

        # Gather hashes for the architecture package lists.
        md5s = []
        sha1s = []
        sha256s = []

        date = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S UTC')

        for root, _, files in os.walk(mainDir):
            for file in files:
                fullPath = os.path.join(root, file)
                displayPath = fullPath[len(self.folder):].lstrip('/')

                md5, sha1, sha256 = Utils.getAllHashes(fullPath)
                size = str(os.path.getsize(fullPath))
                md5s.append(' {0} {1} {2}'.format(md5, size, displayPath))
                sha1s.append(' {0} {1} {2}'.format(sha1, size, displayPath))
                sha256s.append(' {0} {1} {2}'.format(sha256, size, displayPath))

        # Save the final package list, signing
        release = '\n'.join([
            'Origin: linux-kernel', 'Label: linux-kernel', 'Suite: {0}'.format(self.name), 'Codename: {0}'.format(self.name), 'Date: {0}'.format(date),
            'Architectures: {0}'.format(' '.join(self.architectures)), 'Components: main', 'Description: {0}'.format(self.description),
            'MD5Sum:\n{0}'.format('\n'.join(md5s)), 'SHA1:\n{0}'.format('\n'.join(sha1s)), 'SHA256:\n{0}'.format('\n'.join(sha256s))
        ])

        with open(os.path.join(self.folder, 'Release'), 'w') as file:
            file.write(release)

        with open(os.path.join(self.folder, 'InRelease'), 'w') as file:
            try:
                file.write(str(gpg.sign(release, keyid=self.pkgList.gpgKey, passphrase=self.pkgList.gpgPassword)))
            except:
                self.log("Couldn't sign InRelease :( Check your GPG keys!")

        with open(os.path.join(self.folder, 'Release.gpg'), 'w') as file:
            try:
                file.write(str(gpg.sign(release, detach=True, keyid=self.pkgList.gpgKey, passphrase=self.pkgList.gpgPassword)))
            except:
                self.log("Couldn't sign Release.gpg :( Check your GPG keys!")
