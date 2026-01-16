# web-scraper-y-combinator

This project scrapes approximately 500 startups from the Y Combinator directory by leveraging the Algolia API used by the website for efficient data retrieval. Founder names and LinkedIn URLs are enriched by scraping individual company profile pages and extracting embedded JSON data, while long descriptions are summarized using a Hugging Face Transformer-based summarization model. 

The full summarization process takes roughly 15 minutes to complete for all 500 company profiles on CPU, and the final dataset is exported as a clean, labeled CSV file.