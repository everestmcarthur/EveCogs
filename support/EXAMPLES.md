# Support Cog - Configuration Examples

## Example Configurations for Different Server Types

### 1. Small Community Server

**Use Case:** Simple support system with one channel

```bash
[p]supportset enable
[p]supportset addcategory support #staff-support Questions and support
[p]supportset defaultcategory support
[p]supportset setemoji support 💬
[p]supportset setgreeting support Thanks for reaching out! We'll respond as soon as possible.
```

**Result:** Users send `[p]contact <message>` → goes to #staff-support

---

### 2. Gaming Server

**Use Case:** Different support for different game aspects

```bash
# Enable and create categories
[p]supportset enable
[p]supportset addcategory general #general-support General questions
[p]supportset addcategory gameplay #gameplay-help Gameplay questions
[p]supportset addcategory bugs #bug-reports Report bugs
[p]supportset addcategory appeals #appeals Ban appeals

# Set emojis
[p]supportset setemoji general 💬
[p]supportset setemoji gameplay 🎮
[p]supportset setemoji bugs 🐛
[p]supportset setemoji appeals ⚖️

# Custom greetings
[p]supportset setgreeting gameplay Our helpers will assist you shortly!
[p]supportset setgreeting bugs Thank you for reporting! We'll investigate this.
[p]supportset setgreeting appeals Your appeal will be reviewed within 48 hours.

# Settings
[p]supportset requirecategory true
[p]supportset logchannel #support-logs
[p]supportset defaultcategory general
```

---

### 3. Business/Professional Server

**Use Case:** Department-based support with anonymity

```bash
# Setup categories
[p]supportset enable
[p]supportset addcategory sales #sales-inquiries Sales and pricing
[p]supportset addcategory technical #tech-support Technical support
[p]supportset addcategory billing #billing-support Billing and payments
[p]supportset addcategory general #general-support General inquiries

# Emojis
[p]supportset setemoji sales 💼
[p]supportset setemoji technical 🔧
[p]supportset setemoji billing 💳
[p]supportset setemoji general 📝

# Professional greetings
[p]supportset setgreeting sales Thank you for your interest! A sales representative will contact you within 24 hours.
[p]supportset setgreeting technical Our technical team has received your request and will respond shortly.
[p]supportset setgreeting billing Your billing inquiry has been received. Response time: 1-2 business days.

# Professional settings
[p]supportset anonymous false
[p]supportset showinfo true
[p]supportset embed true
[p]supportset requirecategory true
[p]supportset logchannel #support-audit
```

---

### 4. Community Moderation Server

**Use Case:** Anonymous reporting and moderation

```bash
# Setup
[p]supportset enable
[p]supportset addcategory report #user-reports Report users
[p]supportset addcategory appeal #mod-appeals Appeal mod actions
[p]supportset addcategory question #mod-questions Moderation questions

# Emojis
[p]supportset setemoji report 🚨
[p]supportset setemoji appeal ⚖️
[p]supportset setemoji question ❓

# Anonymous settings for user safety
[p]supportset anonymous true
[p]supportset showinfo false

# Greetings
[p]supportset setgreeting report Thank you for your report. Moderators will investigate.
[p]supportset setgreeting appeal Your appeal has been submitted and will be reviewed.

# Settings
[p]supportset requirecategory true
[p]supportset logchannel #mod-logs
[p]supportset embed true
```

---

### 5. Educational/Tutorial Server

**Use Case:** Help system for learning community

```bash
# Categories
[p]supportset enable
[p]supportset addcategory beginner #beginner-help Beginner questions
[p]supportset addcategory advanced #advanced-help Advanced topics
[p]supportset addcategory projects #project-help Project assistance
[p]supportset addcategory resources #resource-requests Resource requests

# Emojis
[p]supportset setemoji beginner 🌱
[p]supportset setemoji advanced 🎓
[p]supportset setemoji projects 💡
[p]supportset setemoji resources 📚

# Encouraging greetings
[p]supportset setgreeting beginner Great question! Our community mentors will help you out.
[p]supportset setgreeting advanced Excellent question! Let's dive into it.
[p]supportset setgreeting projects Excited to see your project! We'll take a look.

# Settings
[p]supportset requirecategory false  # Allow flexible categorization
[p]supportset defaultcategory beginner
[p]supportset showinfo true
[p]supportset anonymous false
```

---

### 6. Large Multi-Purpose Server

**Use Case:** Comprehensive support system

```bash
# Create all categories
[p]supportset enable

# Support categories
[p]supportset addcategory general #general-support General questions
[p]supportset addcategory technical #tech-support Technical issues
[p]supportset addcategory events #event-support Event-related questions
[p]supportset addcategory partnerships #partnerships Partnership inquiries
[p]supportset addcategory billing #billing Billing and donations

# Moderation categories  
[p]supportset addcategory reports #user-reports Report users
[p]supportset addcategory appeals #ban-appeals Ban appeals
[p]supportset addcategory feedback #feedback Feedback and suggestions

# Set all emojis
[p]supportset setemoji general 💬
[p]supportset setemoji technical 🔧
[p]supportset setemoji events 🎉
[p]supportset setemoji partnerships 🤝
[p]supportset setemoji billing 💳
[p]supportset setemoji reports 🚨
[p]supportset setemoji appeals ⚖️
[p]supportset setemoji feedback 💡

# Default settings
[p]supportset defaultcategory general
[p]supportset requirecategory true
[p]supportset logchannel #support-logs
[p]supportset embed true
[p]supportset showinfo true
[p]supportset anonymous false
```

---

## Common Staff Workflows

### Handling a Support Request

1. **User sends:** `[p]contact I can't access my account`
2. **Message appears in category channel** with user info
3. **Staff investigates** the issue
4. **Staff replies:** `[p]dm @User We've reset your account, try logging in now`
5. **User receives** the DM reply
6. **All logged** in #support-logs (if configured)

### Blocking an Abusive User

```bash
# After receiving spam/abuse
[p]supportset block @SpamUser

# User can no longer contact support
# To unblock later:
[p]supportset unblock @SpamUser
```

### Checking Current Setup

```bash
# View all settings and categories
[p]supportset list

# This shows:
# - Enabled status
# - All categories and their channels
# - Current settings (anonymous, embeds, etc.)
# - Log channel
```

---

## Pro Tips

### 1. Category Strategy
- **Keep it simple** - Start with 2-3 categories
- **Clear names** - Use obvious category names
- **Good emojis** - Pick recognizable emojis that match the purpose

### 2. Greetings
- **Set expectations** - Mention response times
- **Be welcoming** - Friendly tone encourages good interactions
- **Be specific** - Different greetings for different categories

### 3. Settings
- **Anonymous mode** - Use for sensitive topics (reports, appeals)
- **Require category** - Enable for large servers with many categories
- **Show info** - Disable for anonymous support, enable for personal support

### 4. Logging
- **Always enable** - Helps track support quality and history
- **Separate channel** - Keep logs in admin-only channel
- **Review regularly** - Monitor for patterns and issues

---

## Troubleshooting

### Users can't contact support
```bash
# Check if enabled
[p]supportset list

# Enable if needed
[p]supportset enable

# Ensure category exists
[p]supportset addcategory general #support
```

### Messages not showing up
```bash
# Verify channel exists and bot has permission
[p]supportset list

# Update channel if needed
[p]supportset addcategory <name> #new-channel
```

### User blocked accidentally
```bash
[p]supportset unblock @User
```

---

## Migration from Red Built-in

If you're migrating from Red's built-in contact system:

1. **Load the cog:** `[p]load support`
2. **Set up categories:** Start with one category matching your old setup
3. **Test it:** Have staff test with `[p]contact` in DMs
4. **Announce to users:** Let them know about the new system
5. **The cog automatically overrides** the built-in commands

No data migration needed - this is a fresh start with better organization!
