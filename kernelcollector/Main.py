from .PackageCollector import PackageCollector
from .PackageList import PackageList
from .PackageDistribution import PackageDistribution
from .WebhookEmitter import WebhookEmitter
import traceback, json, logging, os, sys

class Main(object):

    def __init__(self):
        if os.path.exists('settings.json'):
            with open('settings.json', 'r') as file:
                self.settings = json.load(file)

        defaultValues = {'repoPath': '/srv/packages', 'gpgKey': 'ABCDEF', 'gpgPassword': 'none', 'distribution': 'sid', 'description': 'Package repository for newest Linux kernels', 'architectures': ['amd64'], 'webhook': None}
        edited = False

        for key, value in defaultValues.items():
            if key not in self.settings:
                self.settings[key] = value
                edited = True

        if edited:
            print('Please edit the settings.json file before running the package collector!')
            self.saveSettings()
            sys.exit()

        self.logger = WebhookEmitter(self.settings['webhook'])

        self.packageList = PackageList(self.logger, self.settings['repoPath'].rstrip('/'), self.settings['gpgKey'], self.settings['gpgPassword'])
        self.packageDist = PackageDistribution(self.logger, self.settings['distribution'], self.settings['architectures'], self.settings['description'])
        self.packageList.addDistribution(self.packageDist)

        self.packageCollector = PackageCollector(self.logger, self.settings['architectures'], self.packageList)

    def runAllBuilds(self):
        # Attempt to run all builds.
        # If something goes wrong, a webhook message will be sent.

        try:
            self.packageCollector.runAllBuilds()
        except:
            self.logger.add('Something went wrong while building packages!', alert=True)
            self.logger.add(traceback.format_exc(), pre=True)
            self.logger.send_all()

    def saveSettings(self):
        with open('settings.json', 'w') as file:
            json.dump(self.settings, file, sort_keys=True, indent=4, separators=(',', ': '))

if __name__ == '__main__':
    logging.basicConfig(format='[%(asctime)s] %(message)s', datefmt='%Y/%m/%d %I:%M:%S %p')
    logging.root.setLevel(logging.INFO)

    main = Main()
    main.runAllBuilds()
