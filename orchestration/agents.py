from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from orchestration.schema import Classification, Verifier
from dotenv import load_dotenv

load_dotenv()

classifier = create_agent(
    model="openrouter:nvidia/nemotron-3.5-lightning:free",
    system_prompt="""
    You are a classification agent.

    Classify the user's message into:
    - gmail-task
    - github-task
    - other

    Extract the user's intent and the arguments
    required to execute the task.
    """,
    tools=[],
    response_format=ToolStrategy(Classification),
    name="Orin Classification Agent",
)


verifier = create_agent(
    model="openrouter:nvidia/nemotron-3.5-lightning:free",
    system_prompt="""
    You are a verifier agent.

    You take a look at the entire graph state, mainly user request and execution results, 
    judge the result and decide whether to return a final response or a route back to the execution

    Extract feedback, retry count and verification result 
    """,
    tools=[],
    response_format=ToolStrategy(Verifier),
    name="Orin Verifier Agent",
)
