from bs4 import BeautifulSoup
from . import Utils
import json, requests, tempfile, shutil, os, time, uuid

class PackageCollector(object):

    def __init__(self, repoPath, architectures, distribution, description, gpgKey, gpgPassword, verbose=True):
        self.repoPath = repoPath
        self.architectures = architectures
        self.distribution = distribution
        self.description = description
        self.gpgKey = gpgKey
        self.gpgPassword = gpgPassword
        self.tmpDir = os.path.join(tempfile.gettempdir(), uuid.uuid4().hex)
        self.verbose = verbose
        self.reloadCache()
        self.setupRepository()

    def log(self, message):
        if self.verbose:
            print(message)

    def runAllBuilds(self):
        # Get all releases and prereleases
        self.log('Checking latest versions of the kernel...')
        releases, prereleases = self.getAllReleases()

        # The newest release is always the last in the list
        release = releases[-1]
        prerelease = prereleases[-1]
        dailyRelease = self.getNewestDailyRelease()

        self.log('Current release: {0}'.format(release))
        self.log('Current release candidate: {0}'.format(prerelease))
        self.log('Current daily build: v{0}'.format(dailyRelease))

        # Create the temporary folder
        if os.path.exists(self.tmpDir):
            shutil.rmtree(self.tmpDir)

        os.makedirs(self.tmpDir)

        # Redownload stable build if necessary
        if self.needToRedownload('linux-current', release):
            self.downloadAndRepackAll(release, release, 'linux-current')
            self.markDownloaded('linux-current', release)

        # Redownload beta (release candidate) build if necessary
        if self.needToRedownload('linux-beta', prerelease):
            self.downloadAndRepackAll(prerelease, prerelease, 'linux-beta')
            self.markDownloaded('linux-beta', prerelease)

        # Redownload devel build if necessary
        if self.needToRedownload('linux-devel', dailyRelease):
            self.downloadAndRepackAll('daily/{0}'.format(dailyRelease), 'v' + dailyRelease, 'linux-devel')
            self.markDownloaded('linux-devel', dailyRelease)

        # Update cache and publish repository
        self.updateCache()
        self.publishRepository()

    def setupRepository(self):
        # Create config folder if necessary
        confPath = os.path.join(self.repoPath, 'conf')

        if not os.path.exists(confPath):
            os.makedirs(confPath)

        # Create necessary files for the repository: options and distributions
        # Warning: these files must end with a newline!
        with open(os.path.join(confPath, 'options'), 'w') as file:
            options = ['verbose', 'basedir {0}'.format(self.repoPath), 'ask-passphrase']
            file.write('\n'.join(options) + '\n')

        with open(os.path.join(confPath, 'distributions'), 'w') as file:
            options = [
                'Origin: linux-kernel', 'Label: linux-kernel', 'Codename: {0}'.format(self.distribution),
                'Architectures: {0}'.format(' '.join(self.architectures)), 'Components: main',
                'Description: {0}'.format(self.description), 'SignWith: {0}'.format(self.gpgKey)
            ]
            file.write('\n'.join(options) + '\n')

    def getAllReleases(self):
        # We use the Ubuntu kernel mainline as the build source.
        # This method will return a list of releases and prereleases, sorted in ascending order.
        with requests.get('https://kernel.ubuntu.com/~kernel-ppa/mainline') as site:
            data = site.content

        soup = BeautifulSoup(data, 'html.parser')
        prereleases = []
        releases = []

        for row in soup.findAll('tr'):
            tds = row.findAll('td')

            if len(tds) != 5:
                continue

            a = tds[1].find('a')

            if not a:
                continue

            name = a.text
            prerelease = '-rc' in name

            # Some Ubuntu specific kernel versions will have to be skipped, for example 2.6.32-xenial
            if len(name) < 2 or name[0] != 'v' or (not name[1].isdigit()) or ('-' in name and not prerelease) or (name.count('-') > 1):
                continue

            # Since we're reading links, they might have trailing slashes
            name = name.rstrip('/')

            if prerelease:
                prereleases.append(name)
            else:
                releases.append(name)

        # Sort the releases in descending order
        prereleases.sort(key=lambda x: Utils.prereleaseToTuple(x[1:]))
        releases.sort(key=lambda x: Utils.releaseToTuple(x[1:]))

        return releases, prereleases

    def getNewestDailyRelease(self):
        # We have to find the newest daily release version
        with requests.get('https://kernel.ubuntu.com/~kernel-ppa/mainline/daily/?C=M;O=D') as site:
            data = site.content

        soup = BeautifulSoup(data, 'html.parser')

        for row in soup.findAll('tr'):
            tds = row.findAll('td')

            if len(tds) != 5:
                continue

            a = tds[1].find('a')

            # The link encapsulated inside the <a> tag and the text of the tag will match for daily releases
            if a and a['href'] == a.text:
                return a.text.rstrip('/')

    def getFiles(self, releaseLink, releaseType):
        with requests.get('https://kernel.ubuntu.com/~kernel-ppa/mainline/{0}'.format(releaseLink)) as site:
            data = site.content

        files = {}
        soup = BeautifulSoup(data, 'html.parser')
        arch = None

        for a in soup.findAll('a'):
            text = a.text

            # We have multiple options.
            # If we've reached a build log, that means that we've switched to a new architecture.
            # If we've reached MainlineBuilds, then we're done with all architectures.
            # If we have a chosen architecture and the file is a .deb package, then it has to be in
            # our list of architectures and it must not be an lpae-based build (we don't package those)
            if text.startswith('BUILD.LOG.'):
                arch = text[len('BUILD.LOG.'):]
                continue
            elif text.endswith('MainlineBuilds'):
                break
            elif not text.endswith('.deb') or not arch:
                continue
            elif arch not in self.architectures:
                continue
            elif '-lpae' in text:
                continue

            foundCurrent = False

            # There are three kinds of packages: images, modules and headers;
            # and they can be either generic, low latency or snapdragon (the processor)
            # The only package that doesn't have a sub type is headers-all, which is archless
            for type in ('image', 'modules', 'headers'):
                if '-{0}-'.format(type) not in text:
                    continue

                for subType in ('generic', 'lowlatency', 'snapdragon'):
                    if '-{0}'.format(subType) in text:
                        files['{0}-{1}-{2}-{3}'.format(releaseType, type, subType, arch)] = text
                        foundCurrent = True
                        break

            if (not foundCurrent) and '-headers-' in text:
                files['{0}-headers-all'.format(releaseType)] = text

        return files

    def downloadAndRepack(self, releaseLink, releaseName, pkgName, filename):
        debFilename = os.path.join(self.tmpDir, pkgName + '.deb')
        extractFolder = os.path.join(self.tmpDir, uuid.uuid4().hex)
        controlFilename = os.path.join(extractFolder, 'DEBIAN', 'control')
        link = 'https://kernel.ubuntu.com/~kernel-ppa/mainline/{0}/{1}'.format(releaseLink, filename)

        # Create a temporary folder for the repackaging
        if os.path.exists(extractFolder):
            shutil.rmtree(extractFolder)

        os.makedirs(extractFolder)

        # Download the .deb
        self.log('Downloading package {0} (release {1})'.format(pkgName, releaseName))
        Utils.downloadFile(link, debFilename)

        # Extract the .deb file
        os.system('dpkg-deb -R {0} {1}'.format(debFilename, extractFolder))
        os.remove(debFilename)

        if not os.path.exists(controlFilename):
            self.log('No control file for {0}...'.format(pkgName))
            return

        # Rewrite the control file
        with open(controlFilename, 'r') as f:
            controlLines = f.read().replace('\r', '').split('\n')

        # We have to rewrite the package name, the version
        # We will also remove all linux based dependencies
        # In addition to this, we will replace conflicts with our own conflicts
        # For example, generic packages will conflict with lowlatency and snapdragon packages
        for i, line in enumerate(controlLines):
            if line.startswith('Package:'):
                controlLines[i] = 'Package: {0}'.format(pkgName)
            elif line.startswith('Version:'):
                controlLines[i] = 'Version: {0}'.format(releaseName[1:])
            elif line.startswith('Depends: '):
                dependencies = [dep for dep in line[len('Depends: '):].split(', ') if not dep.startswith('linux-')]
                controlLines[i] = 'Depends: {0}'.format(', '.join(dependencies))
            elif line.startswith('Conflicts'):
                origConflicts = ['generic', 'lowlatency', 'snapdragon']
                conflicts = [conflict for conflict in origConflicts if conflict not in pkgName]

                for conflict in conflicts:
                    origConflicts.remove(conflict)

                myType = origConflicts[0]
                conflicts = [pkgName.replace(myType, conflict) for conflict in conflicts]
                controlLines[i] = 'Conflicts: {0}'.format(', '.join(conflicts))

        with open(controlFilename, 'w') as f:
            f.write('\n'.join(controlLines))

        # Repack the .deb file
        os.system('dpkg-deb -b {0} {1}'.format(extractFolder, debFilename))

        # Remove the temporary extract folder
        if os.path.exists(extractFolder):
            shutil.rmtree(extractFolder)

    def downloadAndRepackAll(self, releaseLink, releaseName, releaseType):
        # Download the file list for this release
        self.log('Downloading release: {0}'.format(releaseType))

        files = self.getFiles(releaseLink, releaseType)

        # Go through all files
        for pkgName, filename in files.items():
            # Check our cache
            if self.fileCache.get(pkgName, None) == filename:
                self.log('Skipping package {0}.'.format(pkgName))
                continue

            # Download and repack
            self.downloadAndRepack(releaseLink, releaseName, pkgName, filename)
            self.fileCache[pkgName] = filename

        # Update cache
        self.updateCache()

    def reloadCache(self):
        # Reload the cache.
        # We use the cache to avoid redownloading and repackaging files that we've already processed
        try:
            with open('cache.json', 'r') as file:
                self.cache = json.load(file)
        except:
            self.cache = {}

        self.fileCache = self.cache.get('files', {})
        self.releaseCache = self.cache.get('releases', {})

    def updateCache(self):
        # Save the cache to disk.
        self.cache['files'] = self.fileCache
        self.cache['releases'] = self.releaseCache

        with open('cache.json', 'w') as file:
            json.dump(self.cache, file, sort_keys=True, indent=4, separators=(',', ': '))

    def needToRedownload(self, releaseType, releaseName):
        # Checks whether a release has been downloaded before or not
        return self.releaseCache.get(releaseType, None) != releaseName

    def markDownloaded(self, releaseType, releaseName):
        # Mark a release as downloaded.
        # This means that the package collector will not redownload this release again for no reason
        self.releaseCache[releaseType] = releaseName

    def publishRepository(self):
        # If temporary directory doesn't exist, nothing matters
        if not os.path.exists(self.tmpDir):
            return

        # Delete lock file if it exists
        lockFile = os.path.join(self.repoPath, 'db', 'lockfile')

        if os.path.exists(lockFile):
            os.remove(lockFile)

        # Collect all deb files in the temporary folder and run the publish command
        debs = [os.path.join(self.tmpDir, file) for file in os.listdir(self.tmpDir) if file.endswith('.deb')]

        if debs:
            os.system('./reprepro_expect {0} {1} includedeb {2} {3}'.format(self.gpgPassword, self.repoPath, self.distribution, ' '.join(debs)))

        # Delete the temporary folder
        shutil.rmtree(self.tmpDir)
