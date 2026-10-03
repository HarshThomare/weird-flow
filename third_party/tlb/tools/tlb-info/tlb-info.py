from __future__ import annotations
from cpuid import cpuid, cpuid_count

class TLBInfo18:
	page_sizes: tuple[list[str], list[int]]
	partitioning: int
	nr_ways: int
	nr_sets: int
	cache_type: str
	cache_type_opt: str | None
	level: int
	full_associative: bool
	nr_ids_sharing: int
	

	def __init__(self, eax: int, ebx: int, ecx: int, edx: int):
		b_eax = f'{eax:032b}'
		b_ebx = f'{ebx:032b}'
		b_ecx = f'{ecx:032b}'
		b_edx = f'{edx:032b}'
		self.page_sizes = get_page_size(b_ebx)
		self.partitioning = int(b_ebx[-11:-8], 2)
		self.nr_ways = int(b_ebx[:-16], 2)
		self.nr_sets = int(b_ecx, 2)
		self.cache_type, self.cache_type_opt = get_cache_type(b_edx)
		self.level = int(b_edx[-8:-5], 2)
		self.full_associative = bool(int(b_edx[-9], 2))
		self.nr_ids_sharing = int(b_edx[-26:-14], 2)+1

	def __lt__(self, other: TLBInfo18):
		return self.level <= other.level and self.cache_type <= other.cache_type and (self.cache_type_opt is None or other.cache_type_opt is None or self.cache_type_opt < other.cache_type_opt) or \
				self.level == other.level and self.cache_type == other.cache_type and (self.cache_type_opt is None or other.cache_type_opt is None or self.cache_type_opt == other.cache_type_opt) and self.lt_page_sizes(other)
	
	def lt_page_sizes(self, other: TLBInfo18):
		return max(self.page_sizes[1]) < max(other.page_sizes[1])


	def __repr__(self) -> str:
		return self.__str__()

	def __str__(self) -> str:
		return f"{f"L{self.level}{self.cache_type}":5}\t{'+'.join(self.page_sizes[0]):15}\t{f"TLB{f"({self.cache_type_opt})" if self.cache_type_opt is not None else ""}:":11}\t{f"{self.nr_ways * self.nr_sets} entries,":13}\t{f"{self.nr_sets} sets,":9}\t{'full' if self.full_associative else f"{self.nr_ways} way"},\t{self.partitioning} partitions,\t{self.nr_ids_sharing} shared"

def get_page_size(ebx: str) -> str:
	value = int(ebx[-4:], 2)
	out = []
	if value & 1:
		out.append(("4K", 1))
	if value & 2:
		out.append(("2MB", 2))
	if value & 4:
		out.append(("4MB", 4))
	if value & 8:
		out.append(("1GB", 8))
	return tuple(zip(*out))

def get_cache_type(edx: str) -> str:
	value = int(edx[-5:], 2)
	if value == 0b0000:
		return None
	elif value == 0b0001:
		return 'D', None	# data cache
	elif value == 0b0010:
		return 'I', None	# instruction cache
	elif value == 0b0011:
		return 'I+D', None	# unified/shared cache
	elif value == 0b00100:
		return 'D', 'load'	# load only tlb
	elif value == 0b00101:
		return 'D', 'store'	# store only tlb



def check_for_new_tlb_leaf_18(eax: int, ebx: int, ecx: int, edx: int) -> bool:
	for r in [eax, ebx, ecx, edx]:
		for b in r.to_bytes(4):
			if "fe" in hex(b):
				return True
	return False

def tlb_info18_for_subleaf(idx: int):
	eax, ebx, ecx, edx = cpuid_count(0x18, idx)
	return TLBInfo18(eax, ebx, ecx, edx)

def get_tlb_info18():
	eax, ebx, ecx, edx = cpuid(0x2)
	if check_for_new_tlb_leaf_18(eax, ebx, ecx, edx):
		eax, _, _, _ = cpuid_count(0x18, 0)
		infos = []
		for i in range(1, eax+1):
			infos.append(tlb_info18_for_subleaf(i))
		for i in sorted(reversed(infos)):
			print(i)
	else:
		print("Does not have info in leaf 0x18, so cant parse tlb info")

def main():
	get_tlb_info18()

if __name__ == '__main__':
	main()
