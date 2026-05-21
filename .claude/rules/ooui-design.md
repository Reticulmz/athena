## Object-Oriented UI Design

When designing UI, user flows, or information architecture, apply Object-Oriented User Interface (OOUI) principles to maximize UX.

### Core Principles
- **Object-first, action-second**: Identify the objects (nouns) users interact with before defining actions (verbs). Users select an object, then choose what to do with it — never ask "What do you want to do?" before showing objects.
- **Object vs. property distinction**: Determine what deserves to be a first-class object (has its own identity, navigable view, and actions) vs. what is merely a property of another object. E.g., "Maker" is an object (browsable collection with its own detail page), while "weight" is a property of Keyboard.
- **Map to user mental models**: UI objects should reflect real-world concepts users already understand, not internal system structures or database tables.
- **Consistent object representation**: The same object should look and behave consistently across all views and contexts. A Keyswitch card in a list, in search results, and embedded in a Keyboard detail page should share the same visual identity.
- **View composition**: An object's view can embed related objects' views. A Keyboard detail page naturally contains its Keyswitches and Keycaps as nested object views — mirroring Rails nested resources and partials.

### Application Guidelines
- **Navigation structure**: Organize around object types (e.g., Keyboards, Keyswitches, Keycaps), not around tasks or workflows.
- **Collection → Single → Action**: Follow the canonical OOUI view transition — browse a collection, select an object, then act on it.
- **Visibility of objects**: Make objects and their states visible. Avoid hiding information behind unnecessary clicks.

### Anti-Patterns: Task-Oriented UI
Task-oriented UI organizes screens around workflows (verbs) rather than objects (nouns). This feels intuitive to developers but confuses users who think in terms of "things."

- Wizard-style flows that ask "What do you want to do?" before showing any objects.
- Navigation grouped by workflow step (e.g., "Register", "Search", "Compare") instead of by object type.
- Deeply nested forms that force users to define objects without seeing them.
- Disconnecting an object's view from its actions (e.g., separate "view" and "manage" pages for the same entity).
