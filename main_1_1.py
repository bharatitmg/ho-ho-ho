#!/usr/bin/env python3
"""
Main script 3 - Uses PricingExtractor class from main.py
Designed for processing a different set of URLs with custom configuration
"""

import os
import json
import time
import csv
from typing import List, Dict, Optional

# Import the PricingExtractor class from main.py
from main import PricingExtractor, save_checkpoint, load_checkpoint, load_existing_results, get_remaining_urls

def read_urls_from_csv(csv_file_path: str) -> List[Dict]:
    """Read URLs from CSV file"""
    urls = []
    try:
        with open(csv_file_path, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                urls.append({
                    "name": row.get('name', ''),
                    "website": row.get('website', '')
                })
        print(f"📋 Read {len(urls)} URLs from CSV")
    except Exception as e:
        print(f"❌ Error reading CSV file: {e}")
    
    return urls

def main():
    """Main function for processing URLs with custom configuration"""
    print("🚀 Starting Main Script 3 - Custom URL Processing")
    
    # Configuration for main_3.py
    csv_file_path = "urls_1_1.csv"  # Different CSV file
    output_file = 'pricing_results_1_1.json'          # Different output file
    
    # Get environment variables
    XAI_API_KEY = os.getenv("OPENROUTER_API_KEY")
    YOUR_SITE_URL = os.getenv("YOUR_SITE_URL")
    YOUR_SITE_NAME = os.getenv("YOUR_SITE_NAME")
    
    # Validate API key
    if not XAI_API_KEY:
        print("❌ XAI_API_KEY environment variable is required but not set")
        print("💡 Set your API key in environment variables or .env file")
        return None
    
    print(f"📁 Input file: {csv_file_path}")
    print(f"💾 Output file: {output_file}")
    
    # Use context manager to ensure proper cleanup
    with PricingExtractor(
        xai_api_key=XAI_API_KEY,
        your_site_url=YOUR_SITE_URL,
        your_site_name=YOUR_SITE_NAME
    ) as extractor:
        
        # Read all URLs from CSV
        all_urls = read_urls_from_csv(csv_file_path)
        if not all_urls:
            print("❌ No URLs found in CSV file!")
            return
        
        # Load existing results and checkpoint
        existing_results = load_existing_results(output_file)
        checkpoint = load_checkpoint(output_file)
        
        if checkpoint and checkpoint.get('results'):
            # Resume from checkpoint
            results = checkpoint['results']
            processed_count = checkpoint['processed_count']
            remaining_urls = get_remaining_urls(all_urls, results)
            print(f"🔄 Resuming processing: {len(remaining_urls)} URLs remaining")
        else:
            # Start fresh
            results = existing_results
            remaining_urls = get_remaining_urls(all_urls, results)
            processed_count = len(results)
            print(f"🆕 Starting fresh: {len(remaining_urls)} URLs to process")
        
        total_count = len(all_urls)
        successful_count = sum(1 for result in results.values() if result.get('success'))
        
        print(f"\n📊 Progress: {processed_count}/{total_count} processed, {successful_count} successful")
        
        # Process remaining URLs
        for i, item in enumerate(remaining_urls):
            # Clear terminal in local environment only
            if not os.getenv('CI') and not os.getenv('GITHUB_ACTIONS'):
                os.system('clear' if os.name == 'posix' else 'cls')
            
            name = item["name"]
            website = item["website"]
            
            print(f"\n{'='*60}")
            print(f"🔄 PROCESSING [{processed_count + i + 1}/{total_count}]: {name}")
            print(f"🌐 URL: {website}")
            print(f"{'='*60}")
            
            if not website or website.strip() == "":
                print("❌ Skipping empty URL")
                results[name] = {"error": "Empty URL", "success": False}
                save_checkpoint(output_file, results, processed_count + i + 1, total_count)
                continue
            
            try:
                # Ensure URL has protocol
                if not website.startswith(('http://', 'https://')):
                    website = 'https://' + website
                
                # Process with timeout (5 minutes per website for main_3)
                import signal
                
                def timeout_handler(signum, frame):
                    raise TimeoutError("Website processing timed out after 5 minutes")
                
                # Set up timeout only on Unix systems (not Windows)
                if hasattr(signal, 'SIGALRM'):
                    signal.signal(signal.SIGALRM, timeout_handler)
                    signal.alarm(300)  # 5 minutes timeout
                
                try:
                    pricing_data = extractor.get_pricing_data(website, name)
                    results[name] = pricing_data
                finally:
                    # Cancel timeout
                    if hasattr(signal, 'SIGALRM'):
                        signal.alarm(0)
                
                if pricing_data.get('success'):
                    successful_count += 1
                    print(f"✅ SUCCESS: {name}")
                else:
                    print(f"❌ FAILED: {name} - {pricing_data.get('error', 'Unknown error')}")
                
                # Print progress update for CI environments
                if os.getenv('CI') or os.getenv('GITHUB_ACTIONS'):
                    print(f"📊 PROGRESS: {processed_count + i + 1}/{total_count} complete, {successful_count} successful")
                    import sys
                    sys.stdout.flush()
                
                # Save checkpoint after each processing
                save_checkpoint(output_file, results, processed_count + i + 1, total_count)
                
                # Short delay to be respectful
                print("⏳ Waiting 2 seconds...")
                time.sleep(2)
                
            except TimeoutError as e:
                error_msg = f"Processing timeout: {str(e)}"
                print(f"⏰ TIMEOUT: {error_msg}")
                results[name] = {
                    "name": name,
                    "website": website,
                    "error": error_msg,
                    "success": False
                }
                save_checkpoint(output_file, results, processed_count + i + 1, total_count)
                time.sleep(2)
                
            except Exception as e:
                error_msg = f"Unexpected error: {str(e)}"
                print(f"💥 ERROR: {error_msg}")
                results[name] = {
                    "name": name,
                    "website": website,
                    "error": error_msg,
                    "success": False
                }
                save_checkpoint(output_file, results, processed_count + i + 1, total_count)
                time.sleep(2)
        
        # Save final results
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        # Clean up checkpoint file after successful completion
        checkpoint_file = output_file.replace('.json', '_checkpoint.json')
        if os.path.exists(checkpoint_file):
            try:
                os.remove(checkpoint_file)
                print("🧹 Checkpoint file cleaned up")
            except:
                pass
        
        print(f"\n{'='*80}")
        print(f"🎊 MAIN SCRIPT 3 PROCESSING COMPLETE!")
        print(f"📊 Total: {len(results)}, ✅ Successful: {successful_count}, ❌ Failed: {len(results) - successful_count}")
        print(f"💾 Final results saved to: {output_file}")
        print(f"📈 Success rate: {(successful_count/len(results)*100):.1f}%")
        print(f"{'='*80}")
        
        # Print summary of failed items
        failed_items = {name: result for name, result in results.items() if not result.get('success')}
        if failed_items:
            print(f"\n📋 Failed items ({len(failed_items)}):")
            for name, result in list(failed_items.items())[:10]:  # Show first 10
                print(f"   - {name}: {result.get('error', 'Unknown error')}")
            if len(failed_items) > 10:
                print(f"   ... and {len(failed_items) - 10} more")
        
        return results

if __name__ == "__main__":
    import signal
    import sys
    
    def signal_handler(signum, frame):
        print(f"\n⚠️ Script interrupted by signal {signum}. Checkpoint saved.")
        print("Run again to resume from where it stopped.")
        sys.exit(1)
    
    # Handle termination signals (Unix only)
    if hasattr(signal, 'SIGINT'):
        signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        results = main()
        if results:
            print("🎉 Script completed successfully!")
        else:
            print("❌ Script completed with errors.")
    except KeyboardInterrupt:
        print(f"\n⚠️ Script interrupted by user. Checkpoint saved. Run again to resume.")
    except Exception as e:
        print(f"\n💥 Script crashed with error: {e}")
        print("Checkpoint saved. Run again to resume from where it stopped.")