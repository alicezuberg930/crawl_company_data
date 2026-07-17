import json

# INPUT_FILE = "doanh_nghiep_chi_tiet.json"
# OUTPUT_FILE = "a_deduplicated.json"

# with open(INPUT_FILE, "r", encoding="utf-8") as f:
#     data = json.load(f)

# seen_tax_codes = set()
# unique_data = []
# duplicates = []

# for obj in data:
#     tax_code = obj.get("tax_code")

#     if tax_code in seen_tax_codes:
#         duplicates.append(obj)
#         continue

#     seen_tax_codes.add(tax_code)
#     unique_data.append(obj)

INPUT_FILE = "danh_muc_nganh_nghe.json"
OUTPUT_FILE = "a_deduplicated.json"

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

seen_business_names = set()
unique_data = []
duplicates = []

for obj in data:
    business_name = obj.get("business_name")

    if business_name in seen_business_names:
        duplicates.append(obj)
        continue

    seen_business_names.add(business_name)
    unique_data.append(obj)

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(unique_data, f, ensure_ascii=False, indent=2)

print(f"Original objects : {len(data)}")
print(f"Unique objects   : {len(unique_data)}")
print(f"Removed duplicates: {len(duplicates)}")

if duplicates:
    print("\nDuplicate tax codes found:")
    for obj in duplicates:
        print(f"- {obj.get('tax_code')} ({obj.get('company_name')})")
else:
    print("\nNo duplicate tax codes found.")