from typing import Optional, Dict, Any
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

class LLMFactory:
    def __init__(self, agent_configs: Optional[Dict[str, Any]] = None):
        # Default configurations if none provided
        self.agent_configs = agent_configs or {
            "default": {"provider": "gemini", "model": "gemini-2.0-flash", "temperature": 0},
            "router": {"provider": "gemini", "model": "gemini-2.0-flash-lite", "temperature": 0},
            "executor": {"provider": "groq", "model": "llama-3.3-70b-versatile", "temperature": 0.7},
        }

    def get_model(self, agent_role: str = "default"):
        config = self.agent_configs.get(agent_role, self.agent_configs["default"])
        provider = config.get("provider", "gemini").lower()
        
        if provider == "gemini":
            return ChatGoogleGenerativeAI(
                model=config.get("model"),
                temperature=config.get("temperature", 0),
                **config.get("extra_params", {})
            )
        elif provider == "groq":
            return ChatGroq(
                model=config.get("model"),
                temperature=config.get("temperature", 0),
                **config.get("extra_params", {})
            )
        else:
            raise ValueError(f"Unknown provider: {provider}")