"""Agent service.

A LangGraph state graph whose router picks one or more specialised worker agents for a
question, each of which answers by calling MCP tools. The workers cannot approve a loan:
the tools they hold are read-only explanations, and the only component that creates an
application is the lending core, driven by the customer's own request.
"""
