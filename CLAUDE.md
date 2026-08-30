# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Database migrations

Alembic migration files in `migrations/versions/` use sequential, zero-padded
numeric revision IDs and filenames instead of Alembic's default random hash
IDs.

- Start numbering at `0001` and increment by one per migration (`0001`,
  `0002`, `0003`, ...).
- The filename prefix, the `revision` value, and the `Revision ID:` line in
  the docstring must all match (e.g. `0003_add_foo_table.py` has
  `revision: str = "0003"`).
- `down_revision` must point to the previous migration's numeric ID, keeping
  a linear chain.
- When generating a new migration (e.g. via `alembic revision --autogenerate`),
  rename the resulting file and edit its `revision`/`down_revision`/docstring
  to follow this scheme before committing.

## APIs and Views
- Don't handle the 500 exceptions in the APIs, don't use try and except for the 500 errors

## Errors and exceptions
- only use try-except when its a very critical case

## Response Style
- Minimize verbose explanations and descriptions in the AI pane
- Provide direct, actionable responses without excessive context
- dont return Key changes section

## Python Type Hints
- Use built-in generics for standard collections: list[int], dict[str, int], set[str], tuple[int, str]
- Use | None instead of Optional[T] for optional values: float | None
- Use | instead of Union[T1, T2] for multiple types: int | str
- Use built-ins whenever possible; typing.List / Dict are legacy
- Use typing only for: Literal, TypedDict, Protocol, Final, ClassVar, NewType, TypeVar, Generic, Callable, Any
- Use None for void
- Never leave a function without a return type

## Imports and modules
- Always use __all__ in __init__ file in each module
- Always import the public needed entities in the __init__ file in the each module
- Always make files private inside the modules if they are not intended to be accessed publicly by using underscore prefix

## Comments & Usage
- Don't write inline comments, unless it's very important
- Don't write docstrings

## Usage Files and README
- Dont generate readme and .md files, or usage scripts

## Evironment variables 
- when getting an envrionment varialbe, use os.envrion as a dictionarity with direct access with sqaured brackets and dont set a default value


## Return Values 
- functions should not return string errors messages in the returned object
- functions those return nothing, should explicitly return None
- functions should not return True/False to indicate success execution

## Database Repositories
- Single method with optional parameters: Use one repository method with optional parameters when the relationship is optional. Keep Python branching for clarity using if statement, but for more complex cases use two different methods

## Structure Guideline for each module in /modules/:
 - Structure: modules/plp/domain/{feature}/ (e.g., learning_session/, assessment_selection/)
 - Inside each feature: public aggregates/components; private infra helpers (_storage.py, _keys.py)
 - Services: keep as application layer composing multiple domain features for views/tasks
 - Repos: accessed by domain components; keep persistence details inside repositories/*


## Enums
- use Enum and dont use Enum, example:
    class AssessmentType(Enum):
        FULL_ASSESSMENT = "full_assessment"
        ADAPTIVE_ASSESSMENT = "adaptive_assessment"
        AI_COMPANION_ASSESSMENT = "ai_companion_assessment"


##  DDD, Value objects: 
- Anything with no id is a pure value object, so it should not be mutable, then it frozen, example: 
    @dataclass(frozen=True)
    class Answer:
        question_id: str
        answer: str


## Abstract methods
- use @abstractmethod decorator for abstract methods, example: 
    class AssessmentSelectorBase:
        @abstractmethod
        def select_assessment(self, **kwargs) -> Assessment:
            pass

## Tests: 
    Newer approach , we will change that: 
        - create integration test flows those cover most of the cases those covers the needed functions starting from higher(service) to lower levels
        - test branched or heavy logic service or any component: 
                    - test happy-path branching of each function
                    - test all error cases
                    - test 1 edge case
        - test afew repositories those are critical (20% of the functions)
        - test all APIs success, validation and error handling
        - dont write direct queries in tests, use repostiories or services
