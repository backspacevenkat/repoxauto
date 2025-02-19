import asyncio
import csv
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Account, Action
from ..services.action_processor import ActionProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/process_actions.log')
    ]
)

logger = logging.getLogger(__name__)

class ActionCSVProcessor:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.processor = ActionProcessor(session)
        self.accounts_cache = {}
        self.results = {
            "total": 0,
            "queued": 0,
            "failed": 0,
            "errors": []
        }

    async def _get_account_by_no(self, account_no: str) -> Optional[Account]:
        """Get account from cache or database"""
        if account_no in self.accounts_cache:
            return self.accounts_cache[account_no]
            
        account = await self.session.execute(
            select(Account).where(Account.account_no == account_no)
        )
        account = account.scalar_one_or_none()
        
        if account:
            self.accounts_cache[account_no] = account
            
        return account

    async def process_csv(self, csv_path: str) -> Dict:
        """Process actions from CSV file"""
        try:
            if not Path(csv_path).exists():
                raise FileNotFoundError(f"CSV file not found: {csv_path}")

            logger.info(f"Processing actions from {csv_path}")
            
            # Read and validate CSV
            actions_to_process = []
            with open(csv_path, 'r') as f:
                reader = csv.DictReader(f)
                
                # Validate headers
                required_fields = {'account_no', 'task_type', 'source_tweet'}
                if not required_fields.issubset(reader.fieldnames):
                    missing = required_fields - set(reader.fieldnames)
                    raise ValueError(f"Missing required columns: {missing}")
                
                # Read all rows
                for row_idx, row in enumerate(reader, start=1):
                    self.results["total"] += 1
                    
                    try:
                        # Basic validation
                        if not all([row['account_no'], row['task_type']]):
                            raise ValueError("Missing required fields")
                            
                        # Validate and map task type
                        # Map task types to action types
                        task_type_map = {
                            'like': 'like_tweet',
                            'rt': 'retweet_tweet',
                            'retweet': 'retweet_tweet',
                            'reply': 'reply_tweet',
                            'quote': 'quote_tweet',
                            'post': 'create_tweet',
                            'dm': 'send_dm',
                            'DM': 'send_dm',  # Add uppercase variant
                            'LIKE': 'like_tweet',
                            'RT': 'retweet_tweet',
                            'RETWEET': 'retweet_tweet',
                            'REPLY': 'reply_tweet',
                            'QUOTE': 'quote_tweet',
                            'POST': 'create_tweet'
                        }
                        
                        # Try original case first, then lowercase
                        action_type = task_type_map.get(row['task_type']) or task_type_map.get(row['task_type'].lower())
                        if not action_type:
                            raise ValueError(f"Invalid task type: {row['task_type']}")
                            
                        # Validate required fields based on action type
                        if action_type in ['reply_tweet', 'quote_tweet', 'create_tweet', 'send_dm']:
                            if not row.get('text_content'):
                                raise ValueError(f"text_content required for {action_type}")
                                
                        if action_type == 'send_dm':
                            if not row.get('user'):
                                raise ValueError("user required for DM action")
                            
                        # Get account
                        account = await self._get_account_by_no(row['account_no'])
                        if not account:
                            raise ValueError(f"Account not found: {row['account_no']}")
                            
                        # Prepare action data
                        action_data = {
                            'account_id': account.id,
                            'action_type': action_type,
                            'tweet_url': None if action_type == 'send_dm' else row['source_tweet'],
                            'priority': int(row.get('priority', 0)),
                            'row': row_idx,
                            'meta_data': {}
                        }
                        
                        # Add fields to meta_data
                        meta_data = {}
                        if row.get('text_content'):
                            meta_data['text_content'] = row['text_content']
                        if row.get('media'):
                            meta_data['media'] = row['media']
                        if row.get('user'):
                            meta_data['user'] = row['user']
                        action_data['meta_data'] = meta_data
                            
                        # Add to processing list
                        actions_to_process.append(action_data)
                        
                    except Exception as e:
                        error_msg = f"Error in row {row_idx}: {str(e)}"
                        logger.error(error_msg)
                        self.results["errors"].append(error_msg)
                        self.results["failed"] += 1
                        continue

            # Process valid actions in batches to avoid concurrent session issues
            logger.info(f"Queueing {len(actions_to_process)} actions")
            
            # Process actions sequentially with delay
            for action in actions_to_process:
                try:
                    # Create a new session for each action
                    async with get_db() as action_session:
                        processor = ActionProcessor(action_session)
                        
                        # Add delay between actions to respect rate limits
                        if self.results["queued"] > 0:
                            await asyncio.sleep(30)  # 30 second delay between actions
                            
                        success, error, queued_action = await processor.queue_action(
                            account_id=action['account_id'],
                            action_type=action['action_type'],
                            tweet_url=action['tweet_url'] if action['action_type'] not in ['create_tweet', 'follow_user', 'send_dm'] else None,
                            user=action['meta_data'].get('user'),
                            priority=action['priority'],
                            meta_data=action['meta_data']
                        )
                        
                        if success:
                            self.results["queued"] += 1
                            logger.info(f"Queued action {queued_action.id} from row {action['row']}")
                        else:
                            error_msg = f"Failed to queue action from row {action['row']}: {error}"
                            logger.error(error_msg)
                            self.results["errors"].append(error_msg)
                            self.results["failed"] += 1
                            
                except Exception as e:
                    error_msg = f"Error processing row {action['row']}: {str(e)}"
                    logger.error(error_msg)
                    self.results["errors"].append(error_msg)
                    self.results["failed"] += 1

            # Generate summary
            success_rate = (self.results["queued"] / self.results["total"]) * 100 if self.results["total"] > 0 else 0
            
            logger.info(f"""
            Processing completed:
            - Total actions: {self.results["total"]}
            - Successfully queued: {self.results["queued"]}
            - Failed: {self.results["failed"]}
            - Success rate: {success_rate:.1f}%
            """)
            
            return self.results
            
        except Exception as e:
            logger.error(f"Error processing CSV: {str(e)}")
            self.results["errors"].append(str(e))
            return self.results

async def process_actions_file(csv_path: str) -> Dict:
    """Main function to process actions CSV file"""
    try:
        # Get database session
        async with get_db() as session:
            processor = ActionCSVProcessor(session)
            return await processor.process_csv(csv_path)
            
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        return {
            "total": 0,
            "queued": 0,
            "failed": 0,
            "errors": [str(e)]
        }

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m backend.app.scripts.process_actions_csv <csv_file>")
        sys.exit(1)
        
    csv_path = sys.argv[1]
    
    try:
        results = asyncio.run(process_actions_file(csv_path))
        
        if results["errors"]:
            print("\nErrors encountered:")
            for error in results["errors"]:
                print(f"- {error}")
                
        sys.exit(0 if results["failed"] == 0 else 1)
        
    except KeyboardInterrupt:
        print("\nProcess interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nFatal error: {str(e)}")
        sys.exit(1)
