from util import median_result, dict_to_csv
from pathlib import Path
import re

pattern = re.compile(r'.*-(\d+)\.csv$')

def main():
	all_dicts = dict()
	directory = Path('./')
	endpath = Path("./results")
	for result_dir in directory.glob('results_*'):
		if result_dir.is_dir():
			results= dict()
			for file in sorted(result_dir.glob('*-*.csv')):
				if file.is_file() and pattern.match(file.name):
					results['-'.join(file.stem.split("-")[:-1])] = median_result(str(file), 2)
			all_dicts[result_dir.name] = results
	for (k,d) in all_dicts.items():
		dict_to_csv(d, f"{endpath / k}.csv")


 
if __name__ == "__main__":
	main()
