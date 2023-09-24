from .package_collector import PackageCollector
from .package_list import PackageList
from .package_distribution import PackageDistribution
from .webhook import WebhookEmitter
import traceback, json, logging, os, sys

class Main(object):

    def __init__(self):
        if os.path.exists('settings.json'):
            with open('settings.json', 'r') as file:
                self.settings = json.load(file)

        default_values = {'repoPath': '/srv/packages', 'gpgKey': 'ABCDEF', 'gpgPassword': 'none', 'distribution': 'sid', 'description': 'Package repository for newest Linux kernels', 'architectures': ['amd64'], 'webhook': None}
        edited = False

        for key, value in default_values.items():
            if key not in self.settings:
                self.settings[key] = value
                edited = True

        if edited:
            print('Please edit the settings.json file before running the package collector!')
            self.save_settings()
            sys.exit()

        self.logger = WebhookEmitter(self.settings['webhook'])

        self.package_list = PackageList(self.logger, self.settings['repoPath'].rstrip('/'), self.settings['gpgKey'], self.settings['gpgPassword'])
        self.package_dist = PackageDistribution(self.logger, self.settings['distribution'], self.settings['architectures'], self.settings['description'])
        self.package_list.add_distribution(self.package_dist)

        self.package_collector = PackageCollector(self.logger, self.settings['architectures'], self.package_list)

    def run_all_builds(self):
        # Attempt to run all builds.
        # If something goes wrong, a webhook message will be sent.

        try:
            self.package_collector.run_all_builds()
        except:
            self.logger.add('Something went wrong while building packages!', alert=True)
            self.logger.add(traceback.format_exc(), pre=True)
            self.logger.send_all()

    def save_settings(self):
        with open('settings.json', 'w') as file:
            json.dump(self.settings, file, sort_keys=True, indent=4, separators=(',', ': '))

if __name__ == '__main__':
    logging.basicConfig(format='[%(asctime)s] %(message)s', datefmt='%Y/%m/%d %I:%M:%S %p')
    logging.root.setLevel(logging.INFO)

    main = Main()
    main.run_all_builds()
