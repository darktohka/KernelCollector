from deb_pkg_tools.package import inspect_package_fields
from distutils.version import LooseVersion
from datetime import datetime
from . import Utils
import shutil, logging, time, os

class PackageList(object):

    def __init__(self, logger, repoPath, gpgKey, gpgPassword):
        self.logger = logger
        self.gpgKey = gpgKey
        self.gpgPassword = gpgPassword
        self.distributions = {}
        self.recentlyAdded = {}
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

    def addDebToPool(self, filename):
        basename = os.path.basename(filename)
        logging.info(f'Adding {basename} to pool...')

        # Create the pool folder if necessary
        poolFolder = os.path.join(self.poolFolder, basename[0])

        if not os.path.exists(poolFolder):
            os.makedirs(poolFolder)

        # Remove any old deb package, and move from original location to pool
        noext, ext = os.path.splitext(basename)
        poolFilename = os.path.join(poolFolder, f'{noext}_tmp{ext}')

        if os.path.exists(poolFilename):
            os.remove(poolFilename)

        shutil.copyfile(filename, poolFilename)
        os.remove(filename)
        self.recentlyAdded[basename] = None # Version to be filled out in getAllReleasesInPool

    def saveAllDistributions(self, letters):
        # Save all distributions
        logging.info('Saving package list...')
        releases = []

        for letter in letters:
            releases.extend(self.getAllReleasesInPool(letter))

        for distribution in self.distributions.values():
            distribution.save(releases)

    def sendEmbeddedReport(self):
        description = [f'**{filename}** has been updated to **v{version}**!' for filename, version in self.recentlyAdded.items() if version is not None]

        if not description:
            return

        description = '\n'.join(description)
        current_date = time.strftime('%Y-%m-%d %H:%M:%S')
        content = {
            'embeds': [{
                'title': 'Your package list has been updated!',
                'description': description,
                'color': 7526106,
                'author': {
                    'name': 'Kernel Collector',
                    'url': 'https://github.com/darktohka/kernelcollector',
                    'icon_url': 'https://i.imgur.com/y6g563D.png'
                },
                'footer': {
                    'text': f'This report has been generated on {current_date}.'
                }
            }]
        }

        self.logger.add_embed(content)
        self.logger.send_all()

    def getAllReleasesInPool(self, letter):
        poolFolder = os.path.join(self.poolFolder, letter)

        # If we have no pool folder, there are no artifacts.
        if not os.path.exists(poolFolder):
            return []

        # Rename all _tmp files
        for file in os.listdir(poolFolder):
            if not file.endswith('_tmp.deb'):
                continue

            fullPath = os.path.join(poolFolder, file)
            newFile = fullPath[:-len('_tmp.deb')] + '.deb'

            if os.path.exists(newFile):
                os.remove(newFile)

            shutil.move(fullPath, newFile)

        # We have to gather all packages
        pkgToVersions = {}

        for file in sorted(os.listdir(poolFolder)):
            fullPath = os.path.join(poolFolder, file)

            if not fullPath.endswith('.deb'):
                os.remove(fullPath)
                continue

            basename = os.path.basename(fullPath)
            logging.info(f'Inspecting {basename}...')

            try:
                data = inspect_package_fields(fullPath)
            except:
                os.remove(fullPath)
                continue

            pkgName = data['Package']
            version = data['Version']
            pkg = pkgToVersions.get(pkgName, {})

            if version in pkg:
                self.logger.add(f'Removing duplicate version {version} from package {pkgName}...')
                self.logger.send_all()
                os.remove(fullPath)
                continue

            if basename in self.recentlyAdded:
                self.recentlyAdded[basename] = version

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
                    self.logger.add(f'Removing old file {os.path.basename(filename)}...')
                    self.logger.send_all()
                    os.remove(filename)

            releases.append([fullPath, data])

        return releases
