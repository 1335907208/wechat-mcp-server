"""Skill distillation - Extract personal communication style from chat history"""

import json
import re
import os
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
from collections import Counter
from datetime import datetime
from pathlib import Path
from jinja2 import Template


@dataclass
class StyleStatistics:
    """Statistical analysis of communication style"""
    avg_message_length: float = 0.0
    median_message_length: float = 0.0
    total_messages: int = 0
    emoji_usage: Dict[str, int] = field(default_factory=dict)
    top_words: List[str] = field(default_factory=list)
    top_phrases: List[str] = field(default_factory=list)
    message_type_distribution: Dict[str, int] = field(default_factory=dict)
    response_time_stats: Dict[str, float] = field(default_factory=dict)
    hourly_distribution: Dict[int, int] = field(default_factory=dict)


@dataclass
class StyleAnalysis:
    """Qualitative analysis of communication style"""
    tone: str = ""
    formality: str = ""
    humor_style: str = ""
    sentence_structure: str = ""
    vocabulary_level: str = ""
    emotional_expression: str = ""
    response_patterns: List[str] = field(default_factory=list)


@dataclass
class FewShotExample:
    """Few-shot example for style imitation"""
    scenario: str
    context: str
    response: str
    category: str = "general"


@dataclass
class StickerUsage:
    """Sticker usage patterns"""
    total_count: int = 0
    frequency_per_100_msgs: float = 0.0
    favorite_types: List[str] = field(default_factory=list)
    context_patterns: Dict[str, str] = field(default_factory=dict)


@dataclass
class DistilledSkill:
    """Complete distilled skill data"""
    profile: Dict[str, str] = field(default_factory=dict)
    statistics: StyleStatistics = field(default_factory=StyleStatistics)
    style_analysis: StyleAnalysis = field(default_factory=StyleAnalysis)
    few_shot_examples: List[FewShotExample] = field(default_factory=list)
    sticker_usage: StickerUsage = field(default_factory=StickerUsage)
    system_prompt: str = ""
    knowledge_domains: List[str] = field(default_factory=list)
    created_at: str = ""
    source_chats: List[str] = field(default_factory=list)


class SkillDistiller:
    """Distill personal communication style from WeChat chat history"""
    
    # Emoji pattern for detection
    EMOJI_PATTERN = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "]+"
    )
    
    # Chinese punctuation
    CHINESE_PUNCT = r'[!?;:,.!?;:,.]'
    
    # Common Chinese phrases
    COMMON_PHRASES = [
        'OK', 'ok', 'Ok', 'oK',
        'OK~', 'ok~', 'OK!', 'ok!',
        'OK.', 'ok.', 'OK~', 'ok~',
        'No', 'no', 'NO',
        'Yes', 'yes', 'YES',
        'No.', 'no.', 'NO.',
        'Yes.', 'yes.', 'YES.',
    ]
    
    def __init__(self, llm_provider: str = "openai", api_key: Optional[str] = None, model: str = ""):
        self.llm_provider = llm_provider
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model or ("gpt-4o-mini" if llm_provider == "openai" else "claude-3-5-sonnet-20241022")
    
    def fetch_chat_history(self, chat_name: str, limit: int = 1000) -> List[Dict[str, Any]]:
        """Fetch chat history using wechat-cli core functions"""
        try:
            from .context import get_context
            from .core.messages import resolve_chat_context, collect_chat_history
            
            ctx = get_context()
            chat_ctx = resolve_chat_context(chat_name, ctx.msg_db_keys, ctx.cache, ctx.decrypted_dir)
            if not chat_ctx or not chat_ctx.get('db_path'):
                return []
            
            names = ctx.get_contact_names()
            lines, _ = collect_chat_history(
                chat_ctx, names, ctx.display_name_for_username,
                start_ts=None, end_ts=None, limit=limit, offset=0,
                msg_type_filter=None, resolve_media=False, db_dir=ctx.db_dir,
            )
            
            # Parse lines into message format
            messages = []
            for line in lines:
                # Format: "[YYYY-MM-DD HH:MM] sender: content"
                import re
                match = re.match(r'\[([^\]]+)\]\s*(.+?):\s*(.+)', line)
                if match:
                    time_str, sender, content = match.groups()
                    messages.append({
                        'content': content,
                        'sender': sender,
                        'is_self': sender == 'me',
                        'create_time': 0,  # Would need proper timestamp parsing
                        'type': 'text'
                    })
            return messages
        
        except Exception as e:
            print(f"Error fetching history: {e}")
        
        return []
    
    def filter_my_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter messages sent by self"""
        return [m for m in messages if m.get('is_self', False)]
    
    def calculate_statistics(self, messages: List[Dict[str, Any]], my_messages: List[Dict[str, Any]]) -> StyleStatistics:
        """Calculate statistical metrics"""
        stats = StyleStatistics()
        
        if not my_messages:
            return stats
        
        # Message lengths
        lengths = [len(m.get('content', '')) for m in my_messages]
        stats.total_messages = len(my_messages)
        stats.avg_message_length = sum(lengths) / len(lengths) if lengths else 0
        sorted_lengths = sorted(lengths)
        mid = len(sorted_lengths) // 2
        stats.median_message_length = (
            sorted_lengths[mid] if len(sorted_lengths) % 2 
            else (sorted_lengths[mid-1] + sorted_lengths[mid]) / 2
        )
        
        # Emoji usage
        emoji_counter = Counter()
        for msg in my_messages:
            content = msg.get('content', '')
            emojis = self.EMOJI_PATTERN.findall(content)
            for emoji in emojis:
                emoji_counter[emoji] += 1
        stats.emoji_usage = dict(emoji_counter.most_common(20))
        
        # Word frequency (Chinese + English)
        word_counter = Counter()
        for msg in my_messages:
            content = msg.get('content', '')
            # Chinese words (2+ chars)
            chinese_words = re.findall(r'[\u4e00-\u9fff]{2,}', content)
            # English words
            english_words = re.findall(r'[a-zA-Z]{3,}', content)
            for word in chinese_words + english_words:
                word_counter[word.lower()] += 1
        stats.top_words = [w for w, _ in word_counter.most_common(30)]
        
        # Message type distribution
        type_counter = Counter()
        for msg in messages:
            msg_type = msg.get('type', 'text')
            type_counter[msg_type] += 1
        stats.message_type_distribution = dict(type_counter)
        
        # Hourly distribution
        hourly_counter = Counter()
        for msg in my_messages:
            timestamp = msg.get('create_time', 0)
            if timestamp:
                try:
                    hour = datetime.fromtimestamp(timestamp).hour
                    hourly_counter[hour] += 1
                except:
                    pass
        stats.hourly_distribution = dict(hourly_counter)
        
        return stats
    
    def extract_few_shots(self, my_messages: List[Dict[str, Any]], all_messages: List[Dict[str, Any]], n: int = 15) -> List[FewShotExample]:
        """Extract representative few-shot examples"""
        examples = []
        
        # Categorize messages
        categories = {
            'technical': [],
            'casual': [],
            'agreement': [],
            'refusal': [],
            'question': [],
            'explanation': [],
        }
        
        for i, msg in enumerate(my_messages):
            content = msg.get('content', '')
            if not content or len(content) < 5:
                continue
            
            # Find context (previous message from other party)
            context = ""
            msg_time = msg.get('create_time', 0)
            for other in reversed(all_messages[:all_messages.index(msg) if msg in all_messages else i]):
                if not other.get('is_self', False):
                    other_time = other.get('create_time', 0)
                    if msg_time - other_time < 300:  # Within 5 minutes
                        context = other.get('content', '')
                        break
            
            # Categorize
            category = self._categorize_message(content)
            categories[category].append((context, content, msg_time))
        
        # Sample from each category
        for category, msgs in categories.items():
            scored = []
            for context, response, _ in msgs:
                score = self._score_example_quality(context, response)
                scored.append((score, context, response))
            
            scored.sort(reverse=True)
            for score, context, response in scored[:n // len(categories) + 1]:
                if score > 0.3:
                    examples.append(FewShotExample(
                        scenario=self._get_scenario(category),
                        context=context[:100] if context else "(direct message)",
                        response=response[:200],
                        category=category
                    ))
        
        return examples[:n]
    
    def _categorize_message(self, content: str) -> str:
        """Categorize message by content"""
        content_lower = content.lower()
        
        # Technical keywords
        tech_keywords = ['code', 'bug', 'api', 'function', 'class', 'error', 'fix', 'implement', 'python', 'javascript', 'java']
        if any(kw in content_lower for kw in tech_keywords):
            return 'technical'
        
        # Agreement
        agreement_keywords = ['ok', 'yes', 'good', 'sure', 'right', 'agree', 'fine', 'deal', 'no problem']
        if any(kw in content_lower for kw in agreement_keywords):
            return 'agreement'
        
        # Refusal
        refusal_keywords = ['no', 'not', "can't", "won't", 'sorry', 'later', 'busy', 'another time']
        if any(kw in content_lower for kw in refusal_keywords):
            return 'refusal'
        
        # Question
        if '?' in content or '?' in content or content.endswith(('?', '??')):
            return 'question'
        
        # Explanation (longer messages)
        if len(content) > 100 and ('because' in content_lower or 'since' in content_lower or 'so' in content_lower):
            return 'explanation'
        
        return 'casual'
    
    def _score_example_quality(self, context: str, response: str) -> float:
        """Score example quality (0-1)"""
        score = 0.0
        
        # Good length
        if 10 < len(response) < 200:
            score += 0.3
        
        # Has context
        if context:
            score += 0.2
        
        # Contains emoji
        if self.EMOJI_PATTERN.search(response):
            score += 0.2
        
        # Not just punctuation
        if re.search(r'[\u4e00-\u9fff]|[a-zA-Z]', response):
            score += 0.2
        
        # Has substance
        if len(response.split()) > 3:
            score += 0.1
        
        return min(score, 1.0)
    
    def _get_scenario(self, category: str) -> str:
        """Get scenario description for category"""
        scenarios = {
            'technical': 'Answering technical questions',
            'casual': 'Casual conversation',
            'agreement': 'Agreeing to requests',
            'refusal': 'Declining requests',
            'question': 'Asking questions',
            'explanation': 'Explaining something',
        }
        return scenarios.get(category, 'General conversation')
    
    def analyze_style_with_llm(self, stats: StyleStatistics, sample_messages: List[str]) -> StyleAnalysis:
        """Use LLM to analyze communication style"""
        
        prompt = f"""Analyze the following communication style based on chat history samples and statistics.

Statistics:
- Average message length: {stats.avg_message_length:.1f} characters
- Total messages: {stats.total_messages}
- Top emojis: {list(stats.emoji_usage.keys())[:10]}
- Top words: {stats.top_words[:15]}

Sample messages (sent by the user):
{chr(10).join(f'- {m}' for m in sample_messages[:30])}

Please analyze and describe:
1. Tone (formal/casual/friendly/professional/mix)
2. Formality level (very formal / somewhat formal / neutral / casual / very casual)
3. Humor style (none / self-deprecating / witty / silly / sarcastic)
4. Sentence structure (short and punchy / medium length / detailed and long)
5. Vocabulary level (simple / moderate / sophisticated / technical)
6. Emotional expression (reserved / moderate / expressive)
7. Response patterns (how they typically start/end messages, handle questions, etc.)

Output as JSON:
{{"tone": "...", "formality": "...", "humor_style": "...", "sentence_structure": "...", "vocabulary_level": "...", "emotional_expression": "...", "response_patterns": ["...", "..."]}}"""

        try:
            response = self._call_llm(prompt)
            # Parse JSON from response
            json_match = re.search(r'\{[^}]+\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return StyleAnalysis(
                    tone=data.get('tone', ''),
                    formality=data.get('formality', ''),
                    humor_style=data.get('humor_style', ''),
                    sentence_structure=data.get('sentence_structure', ''),
                    vocabulary_level=data.get('vocabulary_level', ''),
                    emotional_expression=data.get('emotional_expression', ''),
                    response_patterns=data.get('response_patterns', [])
                )
        except Exception as e:
            print(f"LLM analysis error: {e}")
        
        return StyleAnalysis()
    
    def generate_system_prompt(self, stats: StyleStatistics, analysis: StyleAnalysis, examples: List[FewShotExample]) -> str:
        """Generate system prompt for style imitation"""
        
        template = Template("""# Your Communication Style Profile

You are imitating the communication style of a specific person based on their chat history.

## Language Style
- **Tone**: {{ analysis.tone }}
- **Formality**: {{ analysis.formality }}
- **Humor**: {{ analysis.humor_style }}
- **Sentence Structure**: {{ analysis.sentence_structure }}
- **Vocabulary**: {{ analysis.vocabulary_level }}
- **Emotional Expression**: {{ analysis.emotional_expression }}

## Key Statistics
- Average message length: {{ "%.1f"|format(stats.avg_message_length) }} characters
- Typical emojis used: {{ stats.emoji_usage.keys()|list|join(", ")[:50] }}
- Common words: {{ stats.top_words[:10]|join(", ") }}

## Response Patterns
{% for pattern in analysis.response_patterns %}
- {{ pattern }}
{% endfor %}

## Example Responses
{% for example in examples[:5] %}
**{{ example.scenario }}**
Context: {{ example.context }}
Response: {{ example.response }}
{% endfor %}

## Guidelines for Imitation
1. Keep messages around {{ "%.0f"|format(stats.avg_message_length) }} characters on average
2. Use similar emoji style: {{ analysis.humor_style }}
3. Match the {{ analysis.formality }} formality level
4. Follow the typical response patterns shown above
5. When uncertain, be {{ analysis.tone }} in tone

Remember: You are not just responding - you are responding AS this person would, with their unique voice and style.
""")
        
        return template.render(stats=stats, analysis=analysis, examples=examples)
    
    def _call_llm(self, prompt: str) -> str:
        """Call LLM API"""
        if self.llm_provider == "openai":
            import openai
            client = openai.OpenAI(api_key=self.api_key)
            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000
            )
            return response.choices[0].message.content
        
        elif self.llm_provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)
            response = client.messages.create(
                model=self.model,
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text
        
        else:
            raise ValueError(f"Unknown LLM provider: {self.llm_provider}")
    
    def distill(
        self,
        chat_names: List[str],
        message_limit: int = 500,
        include_stickers: bool = True
    ) -> DistilledSkill:
        """Distill skill from one or more chats"""
        
        all_messages = []
        all_my_messages = []
        
        for chat_name in chat_names:
            messages = self.fetch_chat_history(chat_name, limit=message_limit)
            all_messages.extend(messages)
            all_my_messages.extend(self.filter_my_messages(messages))
        
        if not all_my_messages:
            raise ValueError("No messages found to distill")
        
        # Calculate statistics
        stats = self.calculate_statistics(all_messages, all_my_messages)
        
        # Extract few-shot examples
        examples = self.extract_few_shots(all_my_messages, all_messages)
        
        # Analyze style with LLM
        sample_messages = [m.get('content', '') for m in all_my_messages[:50]]
        analysis = self.analyze_style_with_llm(stats, sample_messages)
        
        # Generate system prompt
        system_prompt = self.generate_system_prompt(stats, analysis, examples)
        
        # Build skill
        skill = DistilledSkill(
            profile={
                "name": "User",
                "style_summary": f"{analysis.tone}, {analysis.formality}, {analysis.sentence_structure}"
            },
            statistics=stats,
            style_analysis=analysis,
            few_shot_examples=examples,
            system_prompt=system_prompt,
            created_at=datetime.now().isoformat(),
            source_chats=chat_names
        )
        
        return skill
    
    def to_json(self, skill: DistilledSkill) -> str:
        """Convert skill to JSON string"""
        return json.dumps(asdict(skill), ensure_ascii=False, indent=2)
    
    def to_markdown(self, skill: DistilledSkill) -> str:
        """Convert skill to Markdown format"""
        template = Template("""# Communication Style Profile

> Generated: {{ skill.created_at }}
> Source chats: {{ skill.source_chats|join(", ") }}

## Style Summary

**{{ skill.profile.style_summary }}**

## Statistics

- **Total messages analyzed**: {{ skill.statistics.total_messages }}
- **Average message length**: {{ "%.1f"|format(skill.statistics.avg_message_length) }} characters
- **Top emojis**: {{ skill.statistics.emoji_usage.keys()|list|join(", ")[:50] }}
- **Common words**: {{ skill.statistics.top_words[:10]|join(", ") }}

## Style Analysis

| Aspect | Description |
|--------|-------------|
| Tone | {{ skill.style_analysis.tone }} |
| Formality | {{ skill.style_analysis.formality }} |
| Humor | {{ skill.style_analysis.humor_style }} |
| Sentence Structure | {{ skill.style_analysis.sentence_structure }} |
| Vocabulary | {{ skill.style_analysis.vocabulary_level }} |
| Emotional Expression | {{ skill.style_analysis.emotional_expression }} |

## Response Patterns

{% for pattern in skill.style_analysis.response_patterns %}
- {{ pattern }}
{% endfor %}

## Example Responses

{% for example in skill.few_shot_examples[:5] %}
### {{ example.scenario }}

**Context**: {{ example.context }}

**Response**: {{ example.response }}

{% endfor %}

---

## System Prompt

```
{{ skill.system_prompt }}
```
""")
        return template.render(skill=skill)
    
    def save_skill(self, skill: DistilledSkill, output_path: str, format: str = "json"):
        """Save skill to file"""
        path = Path(output_path)
        
        if format == "json":
            content = self.to_json(skill)
        else:
            content = self.to_markdown(skill)
        
        path.write_text(content, encoding='utf-8')
        return str(path)
