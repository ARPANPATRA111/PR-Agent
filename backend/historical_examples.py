import re
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field, asdict

from config import settings

logger = logging.getLogger(__name__)

@dataclass
class HistoricalPost:
    week_number: int
    content: str
    summary_section: str = ""
    looking_ahead_section: str = ""
    quote_section: str = ""
    project_links: List[str] = field(default_factory=list)
    showcase_links: List[str] = field(default_factory=list)
    hashtag: str = "#LetsCode2025"
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HistoricalPost":
        return cls(**data)

class HistoricalPostParser:
    BOLD_DIGITS = {
        '𝟎': '0', '𝟏': '1', '𝟐': '2', '𝟑': '3', '𝟒': '4',
        '𝟓': '5', '𝟔': '6', '𝟕': '7', '𝟖': '8', '𝟗': '9',
    }
    
    VALID_BOLD_CHARS = set('𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗')
    
    LOOKING_AHEAD_PATTERN = re.compile(
        r'[*\s]*🔮[*\s]*[𝐋]*[Ll]ooking[*\s]*[𝐀]*[Aa]head[:\s]*',
        re.IGNORECASE | re.UNICODE
    )
    
    QUOTE_PATTERN = re.compile(
        r'[*\s]*💬[*\s]*[𝐐]*[Qq]uote[*\s]*[𝐨of]*[*\s]*[𝐭the]*[*\s]*[𝐖]*[Ww]eek[:\s]*',
        re.IGNORECASE | re.UNICODE
    )
    
    PROGRESS_TRACKING_PATTERN = re.compile(
        r'[*\s]*🔗[*\s]*[𝐏]*[Pp]rogress[*\s]*[𝐓]*[Tt]racking[:\s]*',
        re.IGNORECASE | re.UNICODE
    )
    
    SHOWCASE_PATTERN = re.compile(
        r'[*\s]*💡[*\s]*[𝐒]*[Ss]howcasing[*\s]*[𝐓]*[Tt]he[*\s]*[𝐏]*[Pp]roject[:\s]*',
        re.IGNORECASE | re.UNICODE
    )
    
    RECENT_PROJECT_PATTERN = re.compile(
        r'[*\s]*📂[*\s]*[Rr]ecent[*\s]*[Pp]roject[:\s]*',
        re.IGNORECASE | re.UNICODE
    )
    
    CLOSING_PATTERN = re.compile(
        r"✨[*\s]*Let'?s[*\s]*[𝐜]*code",
        re.IGNORECASE | re.UNICODE
    )
    
    SEPARATOR_PATTERN = re.compile(r'^[-]{3,}$', re.MULTILINE)
    
    def __init__(self, file_path: Optional[str] = None):
        self.file_path = Path(file_path) if file_path else self._find_default_file()
        self.posts: List[HistoricalPost] = []
    
    def _find_default_file(self) -> Path:
        candidates = [
            Path(__file__).parent.parent / "OldProgress.txt",
            Path(__file__).parent / "OldProgress.txt",
            Path.cwd() / "OldProgress.txt",
        ]
        
        for path in candidates:
            if path.exists():
                return path
        
        return candidates[0] 
    
    def parse_file(self) -> List[HistoricalPost]:
        if not self.file_path.exists():
            logger.warning(f"Historical posts file not found: {self.file_path}")
            return []
        
        logger.info(f"Parsing historical posts from: {self.file_path}")
        
        with open(self.file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        raw_posts = self.SEPARATOR_PATTERN.split(content)
        
        for raw_post in raw_posts:
            raw_post = raw_post.strip()
            if not raw_post:
                continue
            
            parsed = self._parse_single_post(raw_post)
            if parsed:
                self.posts.append(parsed)
        
        self.posts.sort(key=lambda p: p.week_number)
        
        logger.info(f"Parsed {len(self.posts)} historical posts (Weeks {self.posts[0].week_number if self.posts else 0} - {self.posts[-1].week_number if self.posts else 0})")
        
        return self.posts
    
    def _parse_single_post(self, raw_text: str) -> Optional[HistoricalPost]:
        week_number = None
        
        for line in raw_text.split('\n'):
            if '🌟' in line and '𝐖𝐞𝐞𝐤-' in line and '𝐑𝐞𝐩𝐨𝐫𝐭' in line:
                idx = line.find('𝐖𝐞𝐞𝐤-')
                if idx >= 0:
                    after = line[idx + len('𝐖𝐞𝐞𝐤-'):]
                    week_part = after.split()[0] if after else ''
                    if all(c in self.VALID_BOLD_CHARS for c in week_part) and week_part:
                        week_number_str = ''.join(self.BOLD_DIGITS.get(c, c) for c in week_part)
                        try:
                            week_number = int(week_number_str)
                            break
                        except ValueError:
                            continue
        
        if week_number is None:
            return None
        
        lines = raw_text.split('\n')
        
        sections = self._identify_sections(lines)
        
        summary_section = self._extract_summary(lines, sections)
        
        looking_ahead = sections.get('looking_ahead', '')
        
        quote = sections.get('quote', '')
        
        project_links = self._extract_links(raw_text, 'github.com')
        showcase_links = self._extract_links(raw_text, 'github.io')
        
        hashtag = "#LetsCode2026" if week_number > 52 else "#LetsCode2025"
        
        return HistoricalPost(
            week_number=week_number,
            content=raw_text,
            summary_section=summary_section,
            looking_ahead_section=looking_ahead,
            quote_section=quote,
            project_links=project_links,
            showcase_links=showcase_links,
            hashtag=hashtag
        )
    
    def _identify_sections(self, lines: List[str]) -> Dict[str, str]:
        sections = {}
        current_section = None
        current_content = []
        
        for line in lines:
            if self.LOOKING_AHEAD_PATTERN.search(line):
                if current_section:
                    sections[current_section] = '\n'.join(current_content).strip()
                current_section = 'looking_ahead'
                current_content = []
            elif self.QUOTE_PATTERN.search(line):
                if current_section:
                    sections[current_section] = '\n'.join(current_content).strip()
                current_section = 'quote'
                current_content = []
            elif self.PROGRESS_TRACKING_PATTERN.search(line):
                if current_section:
                    sections[current_section] = '\n'.join(current_content).strip()
                current_section = 'progress_tracking'
                current_content = []
            elif self.SHOWCASE_PATTERN.search(line):
                if current_section:
                    sections[current_section] = '\n'.join(current_content).strip()
                current_section = 'showcase'
                current_content = []
            elif self.CLOSING_PATTERN.search(line):
                if current_section:
                    sections[current_section] = '\n'.join(current_content).strip()
                current_section = 'closing'
                current_content = []
            elif current_section:
                current_content.append(line)
        
        if current_section:
            sections[current_section] = '\n'.join(current_content).strip()
        
        return sections
    
    def _extract_summary(self, lines: List[str], sections: Dict) -> str:
        content_lines = []
        started = False
        
        for line in lines:
            if '🌟' in line and '𝐖𝐞𝐞𝐤-' in line and '𝐑𝐞𝐩𝐨𝐫𝐭' in line:
                started = True
                continue
            
            if started:
                if any([
                    self.LOOKING_AHEAD_PATTERN.search(line),
                    self.QUOTE_PATTERN.search(line),
                    self.PROGRESS_TRACKING_PATTERN.search(line),
                    self.SHOWCASE_PATTERN.search(line),
                    self.RECENT_PROJECT_PATTERN.search(line),
                ]):
                    break
                content_lines.append(line)
        
        return '\n'.join(content_lines).strip()
    
    def _extract_links(self, text: str, domain: str) -> List[str]:
        pattern = re.compile(rf'https?://[^\s\)]+{domain}[^\s\)]*', re.IGNORECASE)
        return pattern.findall(text)
    
    def get_recent_posts(self, count: int = 5) -> List[HistoricalPost]:
        if not self.posts:
            self.parse_file()
        return self.posts[-count:] if self.posts else []
    
    def get_post_by_week(self, week_number: int) -> Optional[HistoricalPost]:
        if not self.posts:
            self.parse_file()
        
        for post in self.posts:
            if post.week_number == week_number:
                return post
        return None

class HistoricalExamplesDB:
    
    def __init__(self, persist_directory: Optional[str] = None):
        self._posts: Dict[int, Dict[str, Any]] = {}
        self._populated = False
        logger.info("Historical examples DB initialized (in-memory)")
    
    def populate_from_parser(self, parser: HistoricalPostParser) -> int:
        if not parser.posts:
            parser.parse_file()
        
        if not parser.posts:
            logger.warning("No posts to populate")
            return 0
        
        self._posts.clear()
        
        for post in parser.posts:
            self._posts[post.week_number] = {
                "week_number": post.week_number,
                "content": post.summary_section or post.content[:1000],
                "full_content": post.content,
                "has_project_links": len(post.project_links) > 0,
                "has_showcase_links": len(post.showcase_links) > 0,
                "looking_ahead_length": len(post.looking_ahead_section),
                "quote_length": len(post.quote_section)
            }
        
        self._populated = True
        logger.info(f"Populated {len(parser.posts)} historical examples")
        return len(parser.posts)
    
    def find_similar_examples(self, query: str, n_results: int = 3) -> List[Dict[str, Any]]:
        if not self._posts:
            return []
        
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        scored_posts = []
        for week_num, data in self._posts.items():
            content_lower = data['content'].lower()
            score = sum(1 for word in query_words if word in content_lower)
            scored_posts.append((score, data))
        
        scored_posts.sort(key=lambda x: x[0], reverse=True)
        
        return [{
            "week_number": data['week_number'],
            "content": data['content'],
            "distance": None
        } for score, data in scored_posts[:n_results]]
    
    def get_random_examples(self, count: int = 3) -> List[Dict[str, Any]]:
        import random
        
        if not self._posts:
            return []
        
        week_nums = list(self._posts.keys())
        selected = random.sample(week_nums, min(count, len(week_nums)))
        
        return [{
            "week_number": self._posts[w]['week_number'],
            "content": self._posts[w]['content']
        } for w in selected]

LINKEDIN_POST_FORMAT = """
🌟 𝐖𝐞𝐞𝐤-{week_number} 𝐏𝐫𝐨𝐠𝐫𝐞𝐬𝐬 𝐑𝐞𝐩𝐨𝐫𝐭 🚀
{main_content}
{project_section}
🔮 𝐋𝐨𝐨𝐤𝐢𝐧𝐠 𝐀𝐡𝐞𝐚𝐝
{looking_ahead}

💬 𝐐𝐮𝐨𝐭𝐞 𝐨𝐟 𝐭𝐡𝐞 𝐖𝐞𝐞𝐤
{quote}

✨ Let's 𝐜𝐨𝐝𝐞 👨‍💻, 𝐠𝐫𝐨𝐰 🌱, and 𝐚𝐜𝐡𝐢𝐞𝐯𝐞 🎯 together with the hashtag #{hashtag} 🚀🎉
""".strip()


def get_format_template() -> str:
    return LINKEDIN_POST_FORMAT


def get_example_posts() -> List[str]:
    return [
        """🌟 𝐖𝐞𝐞𝐤-𝟓𝟔 𝐏𝐫𝐨𝐠𝐫𝐞𝐬𝐬 𝐑𝐞𝐩𝐨𝐫𝐭 🚀
This was a low-output week overall. I couldn't make much visible progress, but I did spend some time polishing older projects, brainstorming new ideas, and helping friends with their work. A few personal matters also needed attention, so the pace stayed slow but not entirely idle.
📂 Recent Project: https://github.com/ARPANPATRA111/Bullet

🔮 𝐋𝐨𝐨𝐤𝐢𝐧𝐠 𝐀𝐡𝐞𝐚𝐝
College has started, so I'll be going to classes from now on as well. Also a closed sourced project of mine requires some major additions, soo will be doing that in the mean time.

💬 𝐐𝐮𝐨𝐭𝐞 𝐨𝐟 𝐭𝐡𝐞 𝐖𝐞𝐞𝐤
"The computer was born to solve problems that did not exist before." - Bill Gates

✨ Let's 𝐜𝐨𝐝𝐞 👨‍💻, 𝐠𝐫𝐨𝐰 🌱, and 𝐚𝐜𝐡𝐢𝐞𝐯𝐞 🎯 together with the hashtag #𝐋𝐞𝐭𝐬𝐂𝐨𝐝𝐞𝟐𝟎𝟐6 🚀🎉""",
        
        """🌟 𝐖𝐞𝐞𝐤-𝟑𝟗 𝐏𝐫𝐨𝐠𝐫𝐞𝐬𝐬 𝐑𝐞𝐩𝐨𝐫𝐭 🚀
After the intense grind of last week's SIH hackathon, I thought of taking a short break. But the pause didn't last long — I was called in for some urgent Android development work. At first, I was hesitant, but eventually jumped in… and yes, the sleepless nights continued! Right now, I'm still deep into development, making steady progress despite the hectic pace.

🌊 𝐅𝐥𝐨𝐚𝐭-𝐂𝐡𝐚𝐭 𝐀𝐈 [𝐒𝐈𝐇𝟐𝟓𝟎𝟒𝟎]
FloatChat AI is a platform built to make complex oceanographic data from the ARGO program accessible to everyone. Through a conversational interface, users can ask questions in plain English and instantly receive interactive visualizations and clear summaries.

🔑 Key Technical Features:
• Automated Data Pipeline: Converts raw NetCDF files into a queryable format
• AI-Powered Queries: A RAG system with LangChain, ChromaDB, and a local LLM
• Dynamic Visualizations: Interactive dashboard built with Streamlit

💡 𝐒𝐡𝐨𝐰𝐜𝐚𝐬𝐢𝐧𝐠 𝐓𝐡𝐞 𝐏𝐫𝐨𝐣𝐞𝐜𝐭:
📂 GitHub Repository: https://github.com/ARPANPATRA111/Float-Chat

🔮 𝐋𝐨𝐨𝐤𝐢𝐧𝐠 𝐀𝐡𝐞𝐚𝐝
Nothing major is lined up for this week. I'll continue going with the flow while staying focused on ongoing SIH-related development tasks.

💬 𝐐𝐮𝐨𝐭𝐞 𝐨𝐟 𝐭𝐡𝐞 𝐖𝐞𝐞𝐤
"Overthinking is the enemy of action — sometimes, doing is better than pondering."

✨ Let's 𝐜𝐨𝐝𝐞 👨‍💻, 𝐠𝐫𝐨𝐰 🌱, and 𝐚𝐜𝐡𝐢𝐞𝐯𝐞 🎯 together with the hashtag #𝐋𝐞𝐭𝐬𝐂𝐨𝐝𝐞𝟐𝟎𝟐𝟓 🚀🎉"""
    ]

def initialize_historical_examples(file_path: Optional[str] = None) -> HistoricalExamplesDB:
    parser = HistoricalPostParser(file_path)
    parser.parse_file()
    
    db = HistoricalExamplesDB()
    db.populate_from_parser(parser)
    
    return db

if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    parser = HistoricalPostParser()
    posts = parser.parse_file()
    
    print(f"\n✅ Parsed {len(posts)} historical posts")
    
    if posts:
        print(f"   Week range: {posts[0].week_number} - {posts[-1].week_number}")
        print(f"\n📝 Sample post (Week {posts[-1].week_number}):")
        print("-" * 50)
        print(posts[-1].summary_section[:500] + "..." if len(posts[-1].summary_section) > 500 else posts[-1].summary_section)
        print("-" * 50)
    
    if "--populate" in sys.argv:
        db = HistoricalExamplesDB()
        count = db.populate_from_parser(parser)
        print(f"\n✅ Populated database with {count} examples")
        
        if count > 0:
            print("\n🔍 Testing similarity search for 'hackathon project'...")
            similar = db.find_similar_examples("hackathon project", n_results=2)
            for ex in similar:
                print(f"   Week {ex['week_number']}: {ex['content'][:100]}...")
