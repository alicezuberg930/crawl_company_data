- Install library
**python -m pip install requests beautifulsoup4**

- Crawl all categories
**python crawl_danh_muc.py**

- Crawl all business urls
**python crawl_doanh_nghiep.py**

- Crawl all business details
python crawl_masothue.py \
  --input doanh_nghiep_urls.json \
  --output doanh_nghiep_chi_tiet.json