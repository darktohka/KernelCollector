from .PackageCollector import PackageCollector
from .PackageList import PackageList
from .PackageDistribution import PackageDistribution
import traceback, json, os, sys, time
import sys

class Main(object):

    def __init__(self):
        try:
            with open('settings.json', 'r') as file:
                self.settings = json.load(file)
        except:
            self.settings = {}

        defaultValues = {'repoPath': '/var/www/debian', 'gpgKey': 'ABCDEF', 'gpgPassword': 'none', 'distribution': 'sid', 'description': 'Package repository for newest Linux kernels', 'architectures': ['amd64']}
        edited = False

        for key, value in defaultValues.items():
            if key not in self.settings:
                self.settings[key] = value
                edited = True

        if edited:
            print('Please edit the settings.json file before running the package collector!')
            self.saveSettings()
            sys.exit()

        self.packageList = PackageList(self.settings['repoPath'].rstrip('/'), self.settings['gpgKey'], self.settings['gpgPassword'], verbose=True)
        self.packageDist = PackageDistribution(self.settings['distribution'], self.settings['architectures'], self.settings['description'], verbose=True)
        self.packageList.addDistribution(self.packageDist)

        self.packageCollector = PackageCollector(self.settings['architectures'], self.packageList, verbose=True)
        self.logFolder = os.path.join(os.getcwd(), 'logs')

    def runAllBuilds(self):
        # Attempt to run all builds.
        # If something goes wrong, a log file will be created with the error.

        try:
            self.packageCollector.runAllBuilds()
        except:
            log = traceback.format_exc()

            if not os.path.exists(self.logFolder):
                os.makedirs(self.logFolder)

            logFilename = os.path.join(self.logFolder, 'crash-{0}.log'.format(int(time.time())))

            with open(logFilename, 'w') as file:
                file.write(log)

    def saveSettings(self):
        with open('settings.json', 'w') as file:
            json.dump(self.settings, file, sort_keys=True, indent=4, separators=(',', ': '))

if __name__ == '__main__':
    if os.geteuid() != 0:
        print('Please run this program as root!')
        sys.exit()

    main = Main()
    main.runAllBuilds()
