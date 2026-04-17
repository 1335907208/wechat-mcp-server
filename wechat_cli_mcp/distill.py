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
        from .context import get_context
        from .core.messages import resolve_chat_context, collect_chat_history

        ctx = get_context()
        chat_ctx = resolve_chat_context(chat_name, ctx.msg_db_keys, ctx.cache, ctx.decrypted_dir)
        if not chat_ctx:
            raise ValueError(f"Chat not found: {chat_name}")
        if not chat_ctx.get('db_path'):
            raise ValueError(f"No message records for: {chat_name}")

        names = ctx.get_contact_names()
        lines, _ = collect_chat_history(
            chat_ctx, names, ctx.display_name_for_username,
            start_ts=None, end_ts=None, limit=limit, offset=0,
            msg_type_filter=None, resolve_media=False, db_dir=ctx.db_dir,
        )

        is_group = chat_ctx.get('is_group', False)
        # Line formats:
        #   Group:  "[YYYY-MM-DD HH:MM] sender: content"
        #   Private (self): "[YYYY-MM-DD HH:MM] content"  (no sender label)
        #   Private (other): "[YYYY-MM-DD HH:MM] Name: content"
        line_pattern = re.compile(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]\s*(?:(.+?):\s*)?(.+)')
        messages = []
        for line in lines:
            match = line_pattern.match(line)
            if not match:
                continue
            time_str, sender, content = match.groups()
            # In private chats, self messages have no sender label
            is_self = (sender == 'me') if sender else (not is_group and sender is None)
            if sender is None:
                sender = 'me' if not is_group else ''
            # Parse timestamp
            create_time = 0
            try:
                dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M')
                create_time = int(dt.timestamp())
            except ValueError:
                pass
            # Detect message type from content
            msg_type = 'text'
            if content.startswith('[图片]'):
                msg_type = 'image'
            elif content.startswith('[表情]'):
                msg_type = 'sticker'
            elif content.startswith('[链接/文件]'):
                msg_type = 'link'
            elif content.startswith('[通话]'):
                msg_type = 'voip'
            elif content.startswith('[系统]') or content.startswith('[文件]'):
                msg_type = 'system'
            # Skip system messages, revoke messages, and XML content
            if msg_type == 'system':
                continue
            if 'revokemsg' in content or '你撤回了一条消息' in content:
                continue
            if content.strip().startswith('<?xml'):
                continue
            # Skip淘宝/电商链接 (not conversational)
            if '【淘宝】' in content or 'e.tb.cn' in content:
                continue
            # For image/sticker/link/voip, use tag as content summary
            if msg_type != 'text':
                display_content = content
            else:
                display_content = content
            messages.append({
                'content': display_content,
                'sender': sender,
                'is_self': is_self,
                'create_time': create_time,
                'type': msg_type,
            })
        return messages
    
    def filter_my_messages(self, messages: List[Dict[str, Any]], text_only: bool = False) -> List[Dict[str, Any]]:
        """Filter messages sent by self, optionally text-only"""
        result = [m for m in messages if m.get('is_self', False)]
        if text_only:
            result = [m for m in result if m.get('type', 'text') == 'text']
        return result
    
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
        tech_keywords = ['code', 'bug', 'api', 'function', 'class', 'error', 'fix', 'implement',
                         'python', 'javascript', 'java', 'deploy', 'server', 'config', 'debug',
                         '代码', '部署', '服务器', '配置', '调试', '修复', '接口', '测试']
        if any(kw in content_lower for kw in tech_keywords):
            return 'technical'
        
        # Agreement
        agreement_keywords = ['ok', 'yes', 'good', 'sure', 'right', 'agree', 'fine', 'deal',
                              'no problem', '好的', '嗯', '行', '可以', '没问题', '收到', '谢谢',
                              '了解', '明白', '同意']
        if any(kw in content_lower for kw in agreement_keywords):
            return 'agreement'
        
        # Refusal
        refusal_keywords = ['no', 'not', "can't", "won't", 'sorry', 'later', 'busy',
                            'another time', '不行', '不能', '没空', '忙', '算了', '不要']
        if any(kw in content_lower for kw in refusal_keywords):
            return 'refusal'
        
        # Question
        if '?' in content or '？' in content or content.endswith(('?', '？', '??')):
            return 'question'
        
        # Explanation (longer messages)
        if len(content) > 50 and ('because' in content_lower or 'since' in content_lower or
                                   'so' in content_lower or '因为' in content or '所以' in content or
                                   '由于' in content):
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
        """Use LLM to analyze communication style, with rule-based fallback"""
        if self.api_key:
            try:
                return self._analyze_style_with_llm_api(stats, sample_messages)
            except Exception:
                pass
        return self._analyze_style_rule_based(stats, sample_messages)

    def _analyze_style_with_llm_api(self, stats: StyleStatistics, sample_messages: List[str]) -> StyleAnalysis:
        """Use LLM API to analyze communication style"""
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

        response = self._call_llm(prompt)
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
        return StyleAnalysis()

    def _analyze_style_rule_based(self, stats: StyleStatistics, sample_messages: List[str]) -> StyleAnalysis:
        """Rule-based style analysis when no LLM API is available"""
        analysis = StyleAnalysis()

        # Tone: based on emoji usage and message length
        emoji_count = sum(stats.emoji_usage.values())
        emoji_ratio = emoji_count / max(stats.total_messages, 1)
        if emoji_ratio > 0.3:
            analysis.tone = "friendly and casual"
        elif emoji_ratio > 0.1:
            analysis.tone = "friendly, mix of casual and professional"
        else:
            analysis.tone = "professional and direct"

        # Formality: based on average message length and vocabulary
        if stats.avg_message_length < 15:
            analysis.formality = "very casual"
        elif stats.avg_message_length < 30:
            analysis.formality = "casual"
        elif stats.avg_message_length < 60:
            analysis.formality = "neutral"
        elif stats.avg_message_length < 100:
            analysis.formality = "somewhat formal"
        else:
            analysis.formality = "formal"

        # Humor: based on emoji variety
        if len(stats.emoji_usage) > 10:
            analysis.humor_style = "witty and playful"
        elif emoji_ratio > 0.2:
            analysis.humor_style = "silly"
        else:
            analysis.humor_style = "subtle or none"

        # Sentence structure
        if stats.avg_message_length < 20:
            analysis.sentence_structure = "short and punchy"
        elif stats.avg_message_length < 50:
            analysis.sentence_structure = "medium length"
        else:
            analysis.sentence_structure = "detailed and long"

        # Vocabulary
        tech_words = [w for w in stats.top_words if w in
                     ['code', 'bug', 'api', 'function', 'error', 'fix', 'deploy', 'server',
                      'config', 'debug', 'test', 'python', 'java', 'javascript']]
        if len(tech_words) > 5:
            analysis.vocabulary_level = "technical"
        elif stats.avg_message_length > 60:
            analysis.vocabulary_level = "sophisticated"
        elif stats.avg_message_length > 30:
            analysis.vocabulary_level = "moderate"
        else:
            analysis.vocabulary_level = "simple and concise"

        # Emotional expression
        if emoji_ratio > 0.3:
            analysis.emotional_expression = "expressive"
        elif emoji_ratio > 0.1:
            analysis.emotional_expression = "moderate"
        else:
            analysis.emotional_expression = "reserved"

        # Response patterns from samples
        patterns = []
        if sample_messages:
            starts = Counter()
            for m in sample_messages[:50]:
                m = m.strip()
                if not m:
                    continue
                if m.startswith(('嗯', '好', 'OK', 'ok', '收到')):
                    starts['acknowledgment'] += 1
                elif m.startswith(('因为', '所以', '由于')):
                    starts['explanation'] += 1
                elif m.startswith(('@',)):
                    starts['mention_reply'] += 1
                elif '?' in m or '？' in m:
                    starts['question'] += 1
            for pattern_type, count in starts.most_common(3):
                if pattern_type == 'acknowledgment':
                    patterns.append("Often starts with acknowledgment (嗯/好/OK/收到)")
                elif pattern_type == 'explanation':
                    patterns.append("Tends to explain reasoning (因为/所以)")
                elif pattern_type == 'mention_reply':
                    patterns.append("Frequently uses @mentions to reply")
                elif pattern_type == 'question':
                    patterns.append("Often asks questions")
        if not patterns:
            patterns.append("Direct and to-the-point responses")
        analysis.response_patterns = patterns

        return analysis
    
    def generate_skill_body(self, stats: StyleStatistics, analysis: StyleAnalysis, examples: List[FewShotExample]) -> str:
        """Generate SKILL.md body content following Agent Skills specification"""
        # Precompute values
        avg_len_int = int(round(stats.avg_message_length))
        top_emojis = list(stats.emoji_usage.keys())[:5]
        top_examples = examples[:8]

        # Build acknowledgment phrases section
        ack_section = ""
        ack_words = [w for w in ['嗯', '好', 'OK', 'ok', '收到', '好的', '哦哦'] if w in stats.top_words or w in top_emojis]
        if ack_words:
            ack_section = f"When acknowledging or confirming, prefer: {' / '.join(ack_words)}\n"

        # Build question style section
        question_markers = [w for w in ['？', '?'] if w in stats.emoji_usage or w in stats.top_words]

        # Build few-shot examples section
        examples_section = ""
        for ex in top_examples:
            examples_section += f"- **{ex.scenario}**\n  Input: \"{ex.context}\"\n  Output: \"{ex.response}\"\n\n"

        # Build response patterns section
        patterns_section = ""
        for p in analysis.response_patterns:
            patterns_section += f"- {p}\n"

        # Build hourly distribution insights
        hourly_section = ""
        if stats.hourly_distribution:
            sorted_hours = sorted(stats.hourly_distribution.items(), key=lambda x: x[1], reverse=True)
            active_hours = [f"{h}:00" for h, _ in sorted_hours[:4]]
            hourly_section = f"Most active hours: {', '.join(active_hours)}\n"

        # Build message type distribution
        type_section = ""
        if stats.message_type_distribution:
            total_msgs = sum(stats.message_type_distribution.values())
            text_pct = stats.message_type_distribution.get('text', 0) / max(total_msgs, 1) * 100
            sticker_pct = stats.message_type_distribution.get('sticker', 0) / max(total_msgs, 1) * 100
            type_section = f"Text messages: {text_pct:.0f}%, Stickers/Emojis: {sticker_pct:.0f}%\n"

        template = Template("""# WeChat Chat Style Imitation

## When to use
Use this skill when drafting or replying to messages in the user's WeChat communication style. Activate when the user asks you to write messages in their voice, auto-reply in their style, or simulate their chat behavior.

## Style rules
1. Keep messages around {{ avg_len }} characters on average — this person writes short, punchy messages
2. Match the **{{ analysis.formality }}** formality level — avoid overly formal language
3. Adopt a **{{ analysis.tone }}** tone
4. Use **{{ analysis.sentence_structure }}** sentence structure — avoid long paragraphs
5. Vocabulary is **{{ analysis.vocabulary_level }}** — be direct, not verbose
6. Emotional expression is **{{ analysis.emotional_expression }}** — adjust emoji and exclamation usage accordingly
{{ ack_section }}{{ hourly_section }}{{ type_section }}
## Response patterns
{{ patterns_section }}
## How to respond in different scenarios

### Technical discussions
- Be concise and precise; state facts directly without hedging
- Use technical terms naturally without over-explaining
- If you know the answer, say it flatly — don't pad with "I think" or "maybe"

### Casual conversation
- Keep it brief — one or two short sentences max
- Don't over-elaborate; this person doesn't write essays in chat

### Agreeing or confirming
- Use short acknowledgment words, not full sentences
- Avoid repeating back what was said — just confirm

### Declining or pushing back
- Be direct but not rude — raise the concern as a question
- Prefer "can we do X instead?" over "no, I don't want to"

### Asking questions
- Keep questions short and specific
- Prefer direct questions over indirect framing

## Few-shot examples
{{ examples_section }}
## Gotchas
- Do NOT write long paragraphs — this person's average message is {{ avg_len }} characters
- Do NOT use formal honorifics or polite filler — the style is very casual
- Do NOT over-explain — if the answer is simple, give it simply
- DO use acknowledgment words (嗯/好/OK/收到) liberally
- DO use @mentions when replying to specific people in group chats
- DO match the brevity — when in doubt, make it shorter
""")

        return template.render(
            analysis=analysis, avg_len=avg_len_int,
            ack_section=ack_section, hourly_section=hourly_section,
            type_section=type_section, patterns_section=patterns_section,
            examples_section=examples_section,
        )
    
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
        
        errors = []
        for chat_name in chat_names:
            try:
                messages = self.fetch_chat_history(chat_name, limit=message_limit)
                all_messages.extend(messages)
                all_my_messages.extend(self.filter_my_messages(messages))
            except Exception as e:
                errors.append(f"{chat_name}: {e}")
        
        if not all_my_messages:
            detail = "; ".join(errors) if errors else "no self-sent messages found"
            raise ValueError(f"No messages found to distill ({detail})")

        # Use text-only messages for style analysis
        my_text_messages = self.filter_my_messages(all_messages, text_only=True)
        if not my_text_messages:
            my_text_messages = all_my_messages
        
        # Calculate statistics (text-only for cleaner data)
        stats = self.calculate_statistics(all_messages, my_text_messages)
        
        # Extract few-shot examples (text-only)
        examples = self.extract_few_shots(my_text_messages, all_messages)
        
        # Analyze style with LLM (text-only samples)
        sample_messages = [m.get('content', '') for m in my_text_messages[:50]]
        analysis = self.analyze_style_with_llm(stats, sample_messages)
        
        # Generate SKILL.md body content
        skill_body = self.generate_skill_body(stats, analysis, examples)
        
        # Build skill
        skill = DistilledSkill(
            profile={
                "name": "wechat-chat-style",
                "style_summary": f"{analysis.tone}, {analysis.formality}, {analysis.sentence_structure}"
            },
            statistics=stats,
            style_analysis=analysis,
            few_shot_examples=examples,
            system_prompt=skill_body,
            created_at=datetime.now().isoformat(),
            source_chats=chat_names
        )
        
        return skill
    
    def to_json(self, skill: DistilledSkill) -> str:
        """Convert skill to JSON string, including Agent Skills compliant SKILL.md"""
        data = asdict(skill)
        # Add the Agent Skills compliant SKILL.md content
        data['skill_md'] = self.to_markdown(skill)
        return json.dumps(data, ensure_ascii=False, indent=2)
    
    def to_markdown(self, skill: DistilledSkill) -> str:
        """Convert skill to Agent Skills compliant SKILL.md format"""
        # Build YAML frontmatter
        skill_name = skill.profile.get('name', 'wechat-chat-style')
        # Ensure name conforms to spec: lowercase alphanumeric + hyphens
        skill_name = re.sub(r'[^a-z0-9-]', '-', skill_name.lower())
        skill_name = re.sub(r'-+', '-', skill_name).strip('-')
        if not skill_name:
            skill_name = 'wechat-chat-style'

        description = (
            f"Imitate the user's WeChat communication style when drafting or replying to messages. "
            f"Use when the user asks you to write messages in their voice, auto-reply in their style, "
            f"or simulate their chat behavior. Style: {skill.style_analysis.tone}, "
            f"{skill.style_analysis.formality}, {skill.style_analysis.sentence_structure}."
        )
        # Truncate description to 1024 chars per spec
        if len(description) > 1024:
            description = description[:1020] + "..."

        # Build metadata
        source_chats_str = ", ".join(skill.source_chats[:5])
        if len(skill.source_chats) > 5:
            source_chats_str += f" (+{len(skill.source_chats) - 5} more)"

        frontmatter = f"""---
name: {skill_name}
description: {description}
metadata:
  author: wechat-cli
  version: "1.0"
  source-chats: "{source_chats_str}"
  created-at: "{skill.created_at}"
  total-messages: "{skill.statistics.total_messages}"
---"""

        # Body is the skill_body stored in system_prompt field
        body = skill.system_prompt

        return frontmatter + "\n" + body
    
    def save_skill(self, skill: DistilledSkill, output_path: str, format: str = "markdown"):
        """Save skill to file, defaulting to Agent Skills compliant SKILL.md"""
        path = Path(output_path)

        if format == "json":
            content = self.to_json(skill)
        else:
            content = self.to_markdown(skill)
            # Agent Skills spec: markdown output should be named SKILL.md
            if path.is_dir():
                path = path / "SKILL.md"
            elif not path.name.endswith('.md'):
                # If path is a file but not .md, create a directory and put SKILL.md inside
                skill_dir = path.parent / path.stem if path.suffix else path
                skill_dir.mkdir(parents=True, exist_ok=True)
                path = skill_dir / "SKILL.md"

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return str(path)
