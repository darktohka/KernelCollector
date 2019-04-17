from deb_pkg_tools.package import inspect_package_fields
from distutils.version import LooseVersion
from datetime import datetime
from . import Utils
import shutil, os

class PackageList(object):

    def __init__(self, repoPath, gpgKey, gpgPassword, verbose=True):
        self.gpgKey = gpgKey
        self.gpgPassword = gpgPassword
        self.verbose = verbose
        self.distributions = {}
        self.setRepoPath(repoPath)

    def getRepoPath(self):
        return self.repoPath

    def setRepoPath(self, repoPath):
        self.repoPath = repoPath
        self.poolFolder = os.path.join(self.repoPath, 'pool', 'main')
        self.distFolder = os.path.join(self.repoPath, 'dists')

    def getGpgKey(self):
        return self.gpgKey

    def setGpgKey(self, gpgKey):
        self.gpgKey = gpgKey

    def getGpgPassword(self):
        return self.gpgPassword

    def setGpgPassword(self, gpgPassword):
        self.gpgPassword = gpgPassword

    def addDistribution(self, distribution):
        distribution.setPackageList(self)
        self.distributions[distribution.getName()] = distribution

    def getDistribution(self, name):
        return self.distributions[name]

    def log(self, message):
        if self.verbose:
            print(message)

    def addDebToPool(self, filename):
        basename = os.path.basename(filename)
        self.log('Adding {0} to pool...'.format(basename))

        # Create the pool folder if necessary
        poolFolder = os.path.join(self.poolFolder, basename[0])

        if not os.path.exists(poolFolder):
            os.makedirs(poolFolder)

        # Remove any old deb package, and move from original location to pool
        poolFilename = os.path.join(poolFolder, os.path.basename(filename))

        if os.path.exists(poolFilename):
            os.remove(poolFilename)

        shutil.move(filename, poolFilename)

    def saveAllDistributions(self, letter):
        # Save all distributions
        self.log('Saving package list...')
        releases = self.getAllReleasesInPool(letter)

        for distribution in self.distributions.values():
            distribution.save(releases)

    def getAllReleasesInPool(self, letter):
        poolFolder = os.path.join(self.poolFolder, letter)

        # If we have no pool folder, there are no artifacts.
        if not os.path.exists(poolFolder):
            return []
        
        # We have to gather all packages
        pkgToVersions = {}

        for file in os.listdir(poolFolder):
            fullPath = os.path.join(poolFolder, file)

            if not fullPath.endswith('.deb'):
                os.remove(fullPath)
                continue
            
            basename = os.path.basename(fullPath)
            self.log('Inspecting {0}...'.format(basename))
            
            try:
                data = inspect_package_fields(fullPath)
            except:
                os.remove(fullPath)
                continue

            pkgName = data['Package']
            version = data['Version']
            pkg = pkgToVersions.get(pkgName, {})

            if version in pkg:
                self.log('Removing duplicate version {0} from package {1}...'.format(version, pkgName))
                os.remove(fullPath)
                continue
            
            poolFilename = os.path.join(poolFolder, basename)[len(self.repoPath):].lstrip('/')
            md5, sha1, sha256 = Utils.getAllHashes(fullPath)
            data['Filename'] = poolFilename
            data['Size'] = str(os.path.getsize(fullPath))
            data['MD5sum'] = md5
            data['SHA1'] = sha1
            data['SHA256'] = sha256
            pkg[version] = [fullPath, data]
            pkgToVersions[pkgName] = pkg

        releases = []

        # We need to gather the current releases now
        for pkgName, versions in pkgToVersions.items():
            if len(versions) == 1:
                # There is only one version, which is always the newest.
                fullPath, data = list(versions.values())[0]
            else:
                # Look for the newest version
                newestVersion = None
                newestVersionName = None

                for version in versions.keys():
                    if newestVersion is None or LooseVersion(version) > newestVersion:
                        newestVersion = LooseVersion(version)
                        newestVersionName = version

                fullPath, data = versions[newestVersionName]

                # Delete all previous versions from the pool
                for version, pkgList in versions.items():
                    if version == newestVersionName:
                        continue

                    filename = pkgList[0]
                    self.log('Removing old file {0}...'.format(os.path.basename(filename)))
                    os.remove(filename)

            releases.append([fullPath, data])

        return releases