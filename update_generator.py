import re

with open("C:/Mypcb/engine/cognitive_netlist_generator.py", "r", encoding="utf-8") as f:
    content = f.read()

new_prompts = '''SYSTEM_PROMPT = """You are OmniCircuit AI, a generative EDA lead engineer.
Return ONLY valid JSON matching AI_Netlist_v1 schema. Infer missing glue logic, protection,
power rails, level translation, relay isolation, and DRC/ERC constraints.

CRITICAL ENGINEERING CONSTRAINT:
Qorvo DWM3000 UWB modülünün pin aralığı (pitch) standart kütüphanelerdeki gibi 1.27mm DEĞİL, mutlak surette 1.0mm olarak hesaplanmalı ve KiCad'e bu şekilde iletilmelidir! (Add this to the constraints array for DWM3000).

JSON SCHEMA TO FOLLOW EXACTLY:
{
  "schema": "AI_Netlist_v1",
  "project_name": "Project Name",
  "assumptions": ["List of assumed engineering constraints"],
  "components": [
    {
      "ref": "U1",
      "type": "mcu",
      "value": "ESP32-S3 module",
      "manufacturer": "Espressif",
      "part_number": "ESP32-S3-WROOM-1",
      "footprint": "SMD",
      "reason": "Main controller",
      "constraints": ["Constraint 1"]
    }
  ],
  "nets": [
    {
      "net": "+3V3",
      "pins": ["U1.3V3", "R1.1"],
      "net_class": "power",
      "reason": "Main 3.3V supply"
    }
  ],
  "rules": [
    {
      "id": "AC_CLEARANCE",
      "severity": "error",
      "description": "Maintain 8mm clearance",
      "applies_to": ["ALL"]
    }
  ],
  "reasoning_log": [
    {
      "level": "info",
      "message": "Added level shifters",
      "outcome": "accepted"
    }
  ],
  "erc_summary": {
    "status": "pass",
    "checks": ["Checked power rails"]
  }
}
"""


USER_PROMPT_TEMPLATE = """Analyze this hardware request and synthesize an industrial PCB netlist.

User request:
{user_request}

Required cognitive tasks:
- Derive power tree and protection.
- Detect voltage-domain mismatches.
- Add required level shifters, pull-ups, series resistors, optocouplers, and relay drivers.
- Emit components, nets, reasoning_log, and DRC/ERC rules.

Return JSON only with schema AI_Netlist_v1."""'''

content = re.sub(r'SYSTEM_PROMPT = """.*?Return JSON only with schema AI_Netlist_v1."""', new_prompts, content, flags=re.DOTALL)

new_synthesize = '''    def synthesize(self, user_request: str) -> AiNetlist:
        try:
            from engine.ollama_client import OllamaClient
            print("Gemma 4 ile baglanti kuruluyor...")
            client = OllamaClient()
            
            result = client.generate_json(model="gemma4", system_prompt=SYSTEM_PROMPT, user_prompt=USER_PROMPT_TEMPLATE.format(user_request=user_request))
            
            components = [Component(**c) for c in result.get("components", [])]
            nets = [NetConnection(**n) for n in result.get("nets", [])]
            rules = [DesignRule(**r) for r in result.get("rules", [])]
            reasoning = [ReasoningStep(**r) for r in result.get("reasoning_log", [])]
            
            ai_netlist = AiNetlist(
                schema=result.get("schema", "AI_Netlist_v1"),
                project_name=result.get("project_name", "AI_Generated_Project"),
                generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                source_prompt=user_request,
                assumptions=result.get("assumptions", []),
                components=components,
                nets=nets,
                rules=rules,
                reasoning_log=reasoning,
                erc_summary=result.get("erc_summary", {"status": "review_required", "checks": []})
            )
            print("Gemma 4 API basariyla netlist uretti.")
            return ai_netlist
            
        except Exception as e:
            print(f"Gemma API yanit vermedi/hatali: {e}. Yedek (Fallback) deterministik motora geciliyor...")
            return self._synthesize_fallback(user_request)

    def _synthesize_fallback(self, user_request: str) -> AiNetlist:'''

content = content.replace('    def synthesize(self, user_request: str) -> AiNetlist:', new_synthesize)

with open("C:/Mypcb/engine/cognitive_netlist_generator.py", "w", encoding="utf-8") as f:
    f.write(content)
