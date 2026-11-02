# How Does the LLM Know Which Function to Write?

## 🎯 Simple Answer

The LLM knows what function to write because we give it **3 key pieces of information** in the prompt:

1. **What to check** (description in plain English)
2. **Column context** (dtype, sample values, stats)
3. **Rules and format** (how to structure the code)

The LLM has been trained on millions of Python code examples, so it can **generate the right validation logic** based on these inputs.

---

## 📋 Step-by-Step: How It Works

### Step 1: LLM Decides This Column Needs Custom Check

When the LLM reasons about the `TotalCharges` column, it sees:

```python
{
  "dtype": "object",
  "role": "continuous_numeric",
  "missing": "11 (0.16%)",
  "samples": ["29.85", "1889.5", "108.15", " ", "1840.75"],
  "issue": "numeric_stored_as_object"
}
```

The LLM thinks:
> "This column should be numeric but it's stored as text. Python detected 99.84% valid numbers. I need to verify that **after conversion**, all values are in a **valid billing range**."

So it outputs:
```json
{
  "needs_custom_check": true,
  "custom_check_description": "After converting to numeric, verify all values are in range [0, 10000] representing valid billing amounts"
}
```

### Step 2: We Send a Prompt to LLM to Generate Code

Now we ask the LLM to **write Python code** for this specific check:

```python
code_prompt = f"""
Write a Python function to validate a pandas Series column named 'TotalCharges'.

What to check: After converting to numeric, verify all values are in range [0, 10000] representing valid billing amounts

Column dtype: object
Sample values: ["29.85", "1889.5", "108.15", " ", "1840.75"]

Rules:
- Define ONLY: def custom_check(series: pd.Series) -> dict
- Return: {{"passed": bool, "metric": float|str, "details": str}}
- Use only: pd, np, re, built-in Python functions
- NO imports, NO file I/O, NO external calls
- Keep it under 20 lines

Return JSON: {{"code": "<full python code here>"}}
"""
```

### Step 3: LLM Generates the Code

The LLM reads the prompt and **generates appropriate code**:

```json
{
  "code": "def custom_check(series):\n    import pandas as pd\n    \n    # Convert to numeric (coerce errors to NaN)\n    numeric_series = pd.to_numeric(series, errors='coerce')\n    \n    # Check range [0, 10000]\n    valid_mask = (numeric_series >= 0) & (numeric_series <= 10000)\n    valid_count = valid_mask.sum()\n    total_count = len(numeric_series.dropna())\n    \n    valid_ratio = valid_count / total_count if total_count > 0 else 0\n    \n    return {\n        \"passed\": valid_ratio > 0.95,\n        \"metric\": round(valid_ratio, 4),\n        \"details\": f\"{valid_count}/{total_count} values in valid range [0, 10000]\"\n    }"
}
```

---

## 🧠 Why Does the LLM Know How to Write This?

### 1. Training Data
The LLM (Gemini) was trained on:
- **Millions of Python code examples** from GitHub, Stack Overflow, documentation
- **Data validation patterns** (range checks, type conversions, pandas operations)
- **Common data quality scenarios** (missing values, outliers, type mismatches)

### 2. Pattern Recognition
The LLM recognizes patterns:
- **"verify range [0, 10000]"** → needs comparison operators `>=` and `<=`
- **"convert to numeric"** → needs `pd.to_numeric()`
- **"valid billing amounts"** → positive numbers, reasonable upper bound
- **"return metric"** → calculate ratio of valid values

### 3. Context Understanding
The LLM understands:
- **dtype: object** but should be numeric → needs conversion first
- **Sample values** are strings like `"29.85"` → confirms conversion needed
- **"billing amounts"** → business context, should be positive
- **[0, 10000]** → reasonable range for monthly charges

---

## 🎬 Real Examples: Different Columns, Different Functions

### Example 1: Age Column (Range Check)

**Input to LLM:**
```
What to check: Verify age values are in realistic range [0, 120]
Column dtype: int64
Sample values: [25, 34, 56, 23, 150, 89, 45]
```

**LLM Generates:**
```python
def custom_check(series):
    """Check if age values are in valid range."""
    valid_mask = (series >= 0) & (series <= 120)
    valid_count = valid_mask.sum()
    total_count = len(series)
    
    return {
        "passed": valid_count == total_count,
        "metric": valid_count / total_count,
        "details": f"{total_count - valid_count} values outside range [0, 120]"
    }
```

**Why this code?**
- LLM sees "range [0, 120]" → uses comparison operators
- dtype is already int64 → no conversion needed
- Simple range check → straightforward logic

---

### Example 2: Email Column (Pattern Check)

**Input to LLM:**
```
What to check: Verify email format matches standard pattern
Column dtype: object
Sample values: ["john@example.com", "invalid.email", "jane@test.org"]
```

**LLM Generates:**
```python
def custom_check(series):
    """Check if email format is valid."""
    import re
    
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    valid_mask = series.str.match(pattern, na=False)
    valid_count = valid_mask.sum()
    total_count = len(series)
    
    return {
        "passed": valid_count / total_count > 0.95,
        "metric": valid_count / total_count,
        "details": f"{valid_count}/{total_count} valid emails"
    }
```

**Why this code?**
- LLM sees "email format" → knows it needs regex pattern
- dtype is object (strings) → uses `.str.match()`
- "standard pattern" → LLM knows common email regex
- Sample shows `@` symbol → confirms email validation

---

### Example 3: Date Column (Parsing Check)

**Input to LLM:**
```
What to check: Verify date strings can be parsed consistently
Column dtype: object
Sample values: ["2023-01-15", "15/01/2023", "Jan 15 2023", "invalid"]
```

**LLM Generates:**
```python
def custom_check(series):
    """Check if dates can be parsed."""
    import pandas as pd
    
    parsed = pd.to_datetime(series, errors='coerce')
    valid_count = parsed.notna().sum()
    total_count = len(series)
    
    return {
        "passed": valid_count / total_count > 0.99,
        "metric": valid_count / total_count,
        "details": f"{valid_count}/{total_count} parseable dates, {total_count - valid_count} failed"
    }
```

**Why this code?**
- LLM sees "date strings" → uses `pd.to_datetime()`
- "parsed consistently" → needs to check if parsing succeeds
- Multiple formats in samples → uses `errors='coerce'` to handle gracefully

---

### Example 4: Price Column (Business Logic)

**Input to LLM:**
```
What to check: Verify prices are positive and non-zero
Column dtype: float64
Sample values: [29.99, 49.99, -10.50, 0.00, 199.99]
```

**LLM Generates:**
```python
def custom_check(series):
    """Check if prices follow business rules."""
    valid_mask = series > 0
    negative_count = (series < 0).sum()
    zero_count = (series == 0).sum()
    valid_count = valid_mask.sum()
    total_count = len(series)
    
    return {
        "passed": negative_count == 0 and zero_count < total_count * 0.01,
        "metric": valid_count / total_count,
        "details": f"{negative_count} negative, {zero_count} zero prices"
    }
```

**Why this code?**
- LLM sees "positive and non-zero" → checks `> 0`
- "prices" → business context, negative might be refunds but should be rare
- Sample shows `-10.50` and `0.00` → confirms need for these checks

---

## 🔑 Key Factors That Guide the LLM

### 1. The Description (Most Important!)

This tells the LLM **what** to validate:
- "verify range [0, 10000]" → range check
- "verify email format" → regex pattern
- "verify dates can be parsed" → datetime parsing
- "verify positive values" → comparison check

### 2. The Column Type (dtype)

This tells the LLM **how** to process the data:
- `dtype: int64` → already numeric, can compare directly
- `dtype: object` → might need conversion or string operations
- `dtype: float64` → numeric, check for NaN/infinity
- `dtype: datetime64` → already dates, check ranges

### 3. The Sample Values

These give the LLM **concrete examples**:
- `["29.85", "1889.5"]` → numbers stored as strings
- `["john@example.com"]` → email addresses
- `["2023-01-15"]` → date strings
- `[25, 34, 150]` → one outlier (150)

### 4. The Business Context (In Description)

Keywords that guide the LLM:
- "billing amounts" → positive, reasonable upper bound
- "age" → realistic range [0, 120]
- "email" → standard format with @
- "temperature" → might allow negative (Celsius)
- "percentage" → range [0, 100]

---

## 🧪 How to Test If LLM Understands

You can test different prompts:

```python
from agents.llm_client import LLMClient

llm = LLMClient()

# Test 1: Clear description
prompt1 = """
What to check: Verify all values are between 0 and 100
Column: score
dtype: int64
Samples: [85, 92, 105, 78]
"""

# Test 2: Vague description
prompt2 = """
What to check: Check if values are good
Column: score
dtype: int64
Samples: [85, 92, 105, 78]
"""

# Test 3: Complex business logic
prompt3 = """
What to check: Verify that discounts are between 0% and 50%, and no discount exceeds original price
Column: discount_amount
dtype: float64
Samples: [5.99, 12.50, 150.00, 0.00]
Related column: original_price with values [49.99, 99.99, 120.00, 29.99]
"""
```

**Clear descriptions → Better code generation**

---

## 💡 Summary

### How LLM Knows What Function to Write:

1. **Prompt Engineering** - We give clear, structured instructions
2. **Training Data** - LLM learned from millions of code examples
3. **Pattern Recognition** - LLM recognizes data validation patterns
4. **Context Understanding** - dtype, samples, description all guide the LLM

### The Magic Formula:

```
Clear Description + Column Context + Code Rules = Correct Validation Function
```

### Why It Works:

- ✅ LLM has seen similar validation patterns thousands of times
- ✅ Prompt gives specific, actionable instructions
- ✅ Examples (sample values) show concrete cases
- ✅ Business context (billing, age, email) triggers domain knowledge

**The LLM doesn't "magically know" — it's using pattern recognition from training + your specific prompt to generate appropriate code!**

---

## 📚 Related Documents

- `SANDBOX_DEEP_DIVE.md` - Full sandbox mechanism
- `LLM_REASONING_CLARIFICATION.md` - How LLM reasons on all columns
- `test_sandbox_demo.py` - Demo script with examples

---

**Last Updated:** October 22, 2026  
**BIFlow Version:** 2.0.0
