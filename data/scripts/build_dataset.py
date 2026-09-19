"""
EduPath domain knowledge pack — build script.

This is the canonical SOURCE of the curated domain data (design doc §11.5,
Phase 3). Curated content is defined here as plain Python literals (terser
and easier to review/diff than hand-written JSON), then emitted as the JSON
files under data/dataset/ that later phases (backend services, graph loader)
actually read.

Regenerate after editing this file:
    python data/scripts/build_dataset.py

Then validate:
    python data/scripts/validate_dataset.py

Do not hand-edit the JSON files in data/dataset/ — edit this file and
regenerate, so the source of truth stays in one place.
"""
from __future__ import annotations

import json
import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dataset"
GRAPH_VERSION = "v0.1.0-domain-pack"
REVIEWED_BY = "edupath-phase3-curation"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def sk(skill_id, label, aliases, category, kind, description, assessable=True):
    return {
        "skill_id": skill_id,
        "label": label,
        "aliases": aliases,
        "category": category,
        "kind": kind,  # concept | tool | practice
        "description": description,
        "assessable": assessable,
    }


def edge(from_skill, to_skill, type_, strength=None, min_level=1, weight=None,
         source="curated", reviewed_by=REVIEWED_BY):
    e = {
        "from_skill": from_skill,
        "to_skill": to_skill,
        "type": type_,
        "source": source,
        "reviewed_by": reviewed_by,
    }
    if type_ == "PREREQUISITE_OF":
        e["strength"] = strength  # hard | soft
        e["min_level"] = min_level
    if type_ == "RELATED_TO":
        e["weight"] = weight
    return e


def role(role_id, title, description, required):
    # required: list of (skill_id, required_level, weight)
    return {
        "role_id": role_id,
        "title": title,
        "description": description,
        "required_skills": [
            {"skill_id": s, "required_level": lvl, "weight": w} for s, lvl, w in required
        ],
    }


def res(resource_id, title, url, provider, type_, skill_targets, difficulty,
        duration_min, modality, prerequisites, objective, language, cost,
        curation_tier, audience="beginner"):
    # skill_targets: list of (skill_id, level_from, level_to)
    return {
        "resource_id": resource_id,
        "title": title,
        "url": url,
        "provider": provider,
        "type": type_,  # video | article | docs | course | exercise | project | book_chapter
        "skill_targets": [
            {"skill_id": s, "level_from": lf, "level_to": lt} for s, lf, lt in skill_targets
        ],
        "difficulty": difficulty,  # 1-3
        "duration_min": duration_min,
        "modality": modality,  # watch | read | do
        "prerequisite_skill_ids": prerequisites,
        "learning_objective_text": objective,
        "audience": audience,
        "language": language,
        "cost": cost,  # free | freemium | paid
        "curation_tier": curation_tier,  # curated | community | unvetted
        "reviewed_by": REVIEWED_BY,
        "last_verified_at": "2026-09-19",
        "link_status": "ok",
    }


def misc(misconception_id, description, affected_skill, root_prerequisite,
         manifestation, remediation_candidates, severity="medium"):
    return {
        "misconception_id": misconception_id,
        "description": description,
        "affected_skill": affected_skill,
        "root_prerequisite": root_prerequisite,
        "manifestation": manifestation,
        "remediation_candidates": remediation_candidates,
        "severity": severity,  # low | medium | high
    }


def item(item_id, skill_id, difficulty, question, options, explanation, purpose="practice"):
    # options: list of (text, is_key, misconception_id_or_None)
    return {
        "item_id": item_id,
        "skill_id": skill_id,
        "difficulty": difficulty,  # easy | medium | hard
        "purpose": purpose,  # practice | probe | resolution-check | prereq-block
        "question": question,
        "options": [
            {"text": t, "is_key": k, "misconception_id": m} for t, k, m in options
        ],
        "explanation": explanation,
        "generated_by": "curated-seed",
        "validated_by": REVIEWED_BY,
        "graph_version": GRAPH_VERSION,
    }


# --------------------------------------------------------------------------
# 1. SKILLS  (~150-250 target; 3 roles: ML Engineer, Data Analyst, Backend Dev)
# --------------------------------------------------------------------------

SKILLS = [
    # -- tools / collaboration --
    sk("skill.cli_basics", "Command Line / Shell Basics", ["terminal", "bash", "CLI"],
       "tools_collaboration", "tool", "Navigating and operating a Unix-like shell."),
    sk("skill.linux_fundamentals", "Linux Fundamentals", ["Linux", "Unix basics"],
       "tools_collaboration", "concept", "Core Linux OS concepts: processes, filesystem, permissions."),
    sk("skill.git", "Git Version Control", ["Git", "version control"],
       "tools_collaboration", "tool", "Tracking code changes with commits, branches and merges."),
    sk("skill.github_workflow", "GitHub Collaboration Workflow", ["GitHub", "pull requests"],
       "tools_collaboration", "practice", "Collaborating via forks, pull requests and issue tracking."),
    sk("skill.code_review_practice", "Code Review Practice", ["reviewing PRs"],
       "tools_collaboration", "practice", "Giving and acting on structured code review feedback."),
    sk("skill.agile_practices", "Agile / Scrum Practices", ["Scrum", "sprints"],
       "tools_collaboration", "concept", "Iterative delivery practices: sprints, standups, backlogs."),
    sk("skill.documentation_practice", "Technical Documentation", ["writing docs"],
       "tools_collaboration", "practice", "Writing clear READMEs, API docs and design notes."),
    sk("skill.version_control_branching", "Branching Strategies", ["Git flow", "trunk-based dev"],
       "tools_collaboration", "practice", "Choosing and applying a branching model for a team."),

    # -- programming fundamentals --
    sk("skill.programming_fundamentals", "Programming Fundamentals", ["intro to programming"],
       "programming_fundamentals", "concept", "Variables, types, expressions and basic program structure."),
    sk("skill.control_flow", "Control Flow & Loops", ["conditionals", "loops"],
       "programming_fundamentals", "concept", "Branching and iteration constructs."),
    sk("skill.functions_modularity", "Functions & Modularity", ["functions", "modular code"],
       "programming_fundamentals", "concept", "Decomposing programs into reusable functions/modules."),
    sk("skill.oop", "Object-Oriented Programming", ["OOP", "classes and objects"],
       "programming_fundamentals", "concept", "Encapsulation, inheritance and polymorphism."),
    sk("skill.error_handling", "Error Handling & Exceptions", ["exception handling"],
       "programming_fundamentals", "concept", "Detecting, raising and handling runtime errors."),
    sk("skill.debugging", "Debugging Techniques", ["troubleshooting code"],
       "programming_fundamentals", "practice", "Systematic isolation and diagnosis of defects."),
    sk("skill.testing_fundamentals", "Software Testing Fundamentals", ["unit testing", "TDD"],
       "programming_fundamentals", "practice", "Writing tests that verify behavior and catch regressions."),
    sk("skill.design_patterns", "Software Design Patterns", ["design patterns"],
       "programming_fundamentals", "concept", "Reusable solutions to recurring design problems."),
    sk("skill.recursion", "Recursion", ["recursive functions"],
       "programming_fundamentals", "concept", "Solving problems via functions that call themselves."),
    sk("skill.regex", "Regular Expressions", ["regex"],
       "programming_fundamentals", "tool", "Pattern matching and text extraction with regex."),
    sk("skill.json_data_formats", "Data Interchange Formats (JSON/CSV)", ["JSON", "CSV"],
       "programming_fundamentals", "concept", "Reading, writing and validating structured data formats."),
    sk("skill.async_programming", "Asynchronous Programming", ["async/await", "concurrency basics"],
       "programming_fundamentals", "concept", "Non-blocking execution with async/await and event loops."),

    # -- python --
    sk("skill.python", "Python Programming", ["Python", "Python3"],
       "python", "tool", "General-purpose programming in Python."),
    sk("skill.python_data_structures", "Python Data Structures", ["lists", "dicts", "tuples", "sets"],
       "python", "concept", "Python's built-in collection types and their operations."),
    sk("skill.python_oop", "Python OOP", ["Python classes"],
       "python", "concept", "Classes, dunder methods and inheritance in Python."),
    sk("skill.python_venv_packaging", "Python Environments & Packaging", ["virtualenv", "pip", "poetry"],
       "python", "tool", "Isolating dependencies and packaging Python projects."),
    sk("skill.numpy", "NumPy", ["numpy", "numerical computing in Python"],
       "python", "tool", "Vectorized numerical computing with NumPy arrays."),
    sk("skill.pandas", "Pandas", ["pandas", "dataframes"],
       "python", "tool", "Tabular data manipulation with pandas DataFrames."),
    sk("skill.unit_testing_python", "Unit Testing in Python", ["pytest"],
       "python", "practice", "Writing and running unit tests with pytest."),
    sk("skill.web_scraping", "Web Scraping", ["scraping", "requests + BeautifulSoup"],
       "python", "tool", "Extracting data from web pages programmatically."),

    # -- data structures & algorithms --
    sk("skill.dsa_arrays_strings", "Arrays & Strings", ["array manipulation", "string algorithms"],
       "data_structures_algorithms", "concept", "Core operations and patterns on arrays and strings."),
    sk("skill.dsa_linked_lists", "Linked Lists", ["singly/doubly linked lists"],
       "data_structures_algorithms", "concept", "Node-based sequential data structures."),
    sk("skill.dsa_stacks_queues", "Stacks & Queues", ["LIFO", "FIFO"],
       "data_structures_algorithms", "concept", "Stack and queue abstractions and their uses."),
    sk("skill.dsa_hashing", "Hashing & Hash Tables", ["hash maps"],
       "data_structures_algorithms", "concept", "Hash-based lookup structures and collision handling."),
    sk("skill.dsa_trees", "Trees", ["binary trees", "BST"],
       "data_structures_algorithms", "concept", "Hierarchical structures: binary trees, BSTs, traversals."),
    sk("skill.dsa_graphs", "Graphs", ["graph algorithms", "BFS", "DFS"],
       "data_structures_algorithms", "concept", "Graph representations and traversal algorithms."),
    sk("skill.dsa_sorting_searching", "Sorting & Searching Algorithms", ["sorting", "binary search"],
       "data_structures_algorithms", "concept", "Common sorting and searching algorithms and trade-offs."),
    sk("skill.big_o", "Algorithmic Complexity (Big-O)", ["time complexity", "space complexity"],
       "data_structures_algorithms", "concept", "Analyzing algorithm efficiency with asymptotic notation."),

    # -- math foundations --
    sk("skill.algebra_basics", "Algebra Fundamentals", ["basic algebra"],
       "math_foundations", "concept", "Manipulating expressions and solving equations."),
    sk("skill.functions_graphs_math", "Functions & Graphs (Math)", ["mathematical functions"],
       "math_foundations", "concept", "Functions, domain/range, and graphing."),
    sk("skill.calculus_limits", "Limits & Continuity", ["limits"],
       "math_foundations", "concept", "The limit concept underlying calculus."),
    sk("skill.derivatives", "Derivatives", ["differentiation"],
       "math_foundations", "concept", "Rates of change and differentiation rules."),
    sk("skill.chain_rule", "Chain Rule", ["chain rule differentiation", "composite function derivative"],
       "math_foundations", "concept", "Differentiating a composition of functions as a product of derivatives."),
    sk("skill.integrals", "Integrals", ["integration"],
       "math_foundations", "concept", "Antiderivatives and accumulated change."),
    sk("skill.multivariable_calculus", "Multivariable Calculus", ["partial derivatives", "gradients"],
       "math_foundations", "concept", "Calculus with functions of several variables; gradients."),
    sk("skill.linear_algebra_vectors", "Vectors & Vector Spaces", ["vectors"],
       "math_foundations", "concept", "Vector operations, norms and vector spaces."),
    sk("skill.linear_algebra_matrices", "Matrices & Matrix Operations", ["matrix multiplication"],
       "math_foundations", "concept", "Matrix algebra and its geometric interpretation."),
    sk("skill.eigenvalues_eigenvectors", "Eigenvalues & Eigenvectors", ["eigendecomposition"],
       "math_foundations", "concept", "Characteristic vectors/values of linear transformations."),
    sk("skill.optimization_basics", "Optimization Basics", ["gradient descent", "convex optimization basics"],
       "math_foundations", "concept", "Finding function minima/maxima, gradient-based methods."),
    sk("skill.math_for_ml", "Mathematics for Machine Learning", ["ML math foundations"],
       "math_foundations", "concept", "Umbrella grouping of the math skills ML relies on.", assessable=False),

    # -- probability & statistics --
    sk("skill.probability_fundamentals", "Probability Fundamentals", ["probability basics"],
       "probability_statistics", "concept", "Events, random variables and basic probability rules."),
    sk("skill.descriptive_statistics", "Descriptive Statistics", ["mean", "median", "variance"],
       "probability_statistics", "concept", "Summarizing data with central tendency and dispersion."),
    sk("skill.probability_distributions", "Probability Distributions", ["normal distribution", "binomial"],
       "probability_statistics", "concept", "Common discrete/continuous distributions and their properties."),
    sk("skill.inferential_statistics", "Inferential Statistics", ["confidence intervals"],
       "probability_statistics", "concept", "Drawing conclusions about populations from samples."),
    sk("skill.hypothesis_testing", "Hypothesis Testing", ["p-values", "t-tests"],
       "probability_statistics", "concept", "Formal procedure for testing statistical claims."),
    sk("skill.ab_testing", "A/B Testing & Experimentation", ["experiment design"],
       "probability_statistics", "practice", "Designing and analyzing controlled experiments."),
    sk("skill.regression_analysis", "Regression Analysis", ["linear regression", "logistic regression"],
       "probability_statistics", "concept", "Modeling relationships between variables."),
    sk("skill.bayesian_thinking", "Bayesian Reasoning", ["Bayes theorem"],
       "probability_statistics", "concept", "Updating beliefs with evidence via Bayes' theorem."),
    sk("skill.time_series_analysis", "Time Series Analysis", ["seasonality", "trend"],
       "probability_statistics", "concept", "Analyzing data indexed over time."),
    sk("skill.statistics_for_data_analysis", "Statistics for Data Analysis", ["stats foundations"],
       "probability_statistics", "concept", "Umbrella grouping of statistics skills a data analyst needs.",
       assessable=False),

    # -- ML fundamentals --
    sk("skill.ml_fundamentals", "Machine Learning Fundamentals", ["intro to machine learning"],
       "machine_learning_fundamentals", "concept", "What ML is and the standard learning workflow."),
    sk("skill.supervised_learning", "Supervised Learning", ["classification", "regression (ML)"],
       "machine_learning_fundamentals", "concept", "Learning a mapping from labeled examples."),
    sk("skill.unsupervised_learning", "Unsupervised Learning", ["clustering", "dimensionality reduction"],
       "machine_learning_fundamentals", "concept", "Finding structure in unlabeled data."),
    sk("skill.clustering", "Clustering Algorithms", ["k-means", "hierarchical clustering"],
       "machine_learning_fundamentals", "concept", "Grouping similar data points."),
    sk("skill.dimensionality_reduction", "Dimensionality Reduction", ["PCA", "t-SNE"],
       "machine_learning_fundamentals", "concept", "Reducing feature space while preserving structure."),
    sk("skill.model_evaluation", "Model Evaluation & Metrics", ["precision", "recall", "F1", "ROC-AUC"],
       "machine_learning_fundamentals", "concept", "Quantifying model quality with the right metric."),
    sk("skill.overfitting_regularization", "Overfitting & Regularization", ["bias-variance tradeoff"],
       "machine_learning_fundamentals", "concept", "Why models overfit and how regularization helps."),
    sk("skill.cross_validation", "Cross-Validation", ["k-fold CV"],
       "machine_learning_fundamentals", "concept", "Estimating generalization performance robustly."),
    sk("skill.feature_engineering", "Feature Engineering", ["feature construction"],
       "machine_learning_fundamentals", "concept", "Transforming raw data into useful model inputs."),
    sk("skill.decision_trees_ensembles", "Decision Trees & Ensemble Methods", ["random forest", "XGBoost"],
       "machine_learning_fundamentals", "concept", "Tree-based models and ensembling."),
    sk("skill.scikit_learn", "scikit-learn", ["sklearn"],
       "machine_learning_fundamentals", "tool", "Fitting and evaluating classical ML models in Python."),
    sk("skill.hyperparameter_tuning", "Hyperparameter Tuning", ["grid search", "random search"],
       "machine_learning_fundamentals", "practice", "Systematically searching for good hyperparameters."),
    sk("skill.model_interpretability", "Model Interpretability", ["SHAP", "feature importance"],
       "machine_learning_fundamentals", "concept", "Explaining what drives a model's predictions."),

    # -- deep learning --
    sk("skill.deep_learning_fundamentals", "Deep Learning Fundamentals", ["intro to deep learning"],
       "deep_learning", "concept", "Umbrella grouping of core neural-network skills.", assessable=False),
    sk("skill.neural_network_fundamentals", "Neural Network Fundamentals", ["perceptron", "feedforward networks"],
       "deep_learning", "concept", "Layers, weights and forward computation in neural nets."),
    sk("skill.activation_functions", "Activation Functions", ["ReLU", "sigmoid", "softmax"],
       "deep_learning", "concept", "Nonlinearities that give neural nets their expressive power."),
    sk("skill.loss_functions", "Loss Functions", ["cross-entropy loss", "MSE loss"],
       "deep_learning", "concept", "Objectives that quantify prediction error for training."),
    sk("skill.backpropagation", "Backpropagation", ["backprop", "gradient computation in neural nets"],
       "deep_learning", "concept", "Computing gradients through a network via the chain rule."),
    sk("skill.gradient_descent_variants", "Gradient Descent Variants", ["SGD", "Adam optimizer", "momentum"],
       "deep_learning", "concept", "Optimization algorithms used to train neural networks."),
    sk("skill.training_neural_networks", "Training Neural Networks", ["training loop", "epochs and batches"],
       "deep_learning", "practice", "Running the end-to-end loop that fits a neural network."),
    sk("skill.regularization_dl", "Deep Learning Regularization", ["dropout", "batch normalization"],
       "deep_learning", "concept", "Techniques that reduce overfitting in deep nets."),
    sk("skill.batch_normalization", "Batch Normalization", ["batchnorm"],
       "deep_learning", "concept", "Normalizing layer activations to stabilize training."),
    sk("skill.pytorch", "PyTorch", ["PyTorch"],
       "deep_learning", "tool", "Building and training neural networks with PyTorch."),
    sk("skill.tensorflow_keras", "TensorFlow / Keras", ["TensorFlow", "Keras"],
       "deep_learning", "tool", "Building and training neural networks with TensorFlow/Keras."),
    sk("skill.cnn", "Convolutional Neural Networks", ["CNNs", "convnets"],
       "deep_learning", "concept", "Architectures specialized for grid-like (image) data."),
    sk("skill.rnn_sequence_models", "RNNs & Sequence Models", ["LSTM", "GRU"],
       "deep_learning", "concept", "Architectures for sequential/temporal data."),
    sk("skill.transformers_attention", "Transformers & Attention", ["self-attention"],
       "deep_learning", "concept", "Attention-based architectures underlying modern NLP/LLMs."),
    sk("skill.transfer_learning", "Transfer Learning", ["fine-tuning pretrained models"],
       "deep_learning", "concept", "Adapting a pretrained model to a new task."),

    # -- computer vision --
    sk("skill.computer_vision_fundamentals", "Computer Vision Fundamentals", ["intro to CV"],
       "computer_vision", "concept", "Umbrella grouping of computer-vision skills.", assessable=False),
    sk("skill.image_processing_basics", "Image Processing Basics", ["digital image fundamentals"],
       "computer_vision", "concept", "Pixels, color spaces and basic image transforms."),
    sk("skill.opencv", "OpenCV", ["OpenCV"],
       "computer_vision", "tool", "Classical image processing and CV with OpenCV."),
    sk("skill.cnn_image_classification", "Image Classification with CNNs", ["image classifiers"],
       "computer_vision", "practice", "Training a CNN to classify images."),
    sk("skill.object_detection", "Object Detection", ["YOLO", "bounding boxes"],
       "computer_vision", "concept", "Localizing and classifying multiple objects in an image."),
    sk("skill.image_segmentation", "Image Segmentation", ["semantic segmentation"],
       "computer_vision", "concept", "Pixel-level classification of image regions."),

    # -- NLP --
    sk("skill.nlp_and_llms", "NLP & LLMs", ["intro to NLP"],
       "nlp", "concept", "Umbrella grouping of NLP and language-model skills.", assessable=False),
    sk("skill.nlp_fundamentals", "NLP Fundamentals", ["text preprocessing", "tokenization"],
       "nlp", "concept", "Core text-processing concepts for NLP."),
    sk("skill.word_embeddings", "Word Embeddings", ["word2vec", "GloVe"],
       "nlp", "concept", "Dense vector representations of words/tokens."),
    sk("skill.llm_basics", "Large Language Model Basics", ["LLMs", "generative language models"],
       "nlp", "concept", "How modern large language models work at a conceptual level."),
    sk("skill.prompt_engineering", "Prompt Engineering", ["prompt design"],
       "nlp", "practice", "Crafting inputs that reliably steer an LLM's output."),
    sk("skill.huggingface", "Hugging Face Ecosystem", ["transformers library", "HF hub"],
       "nlp", "tool", "Using the Hugging Face libraries/hub for NLP models."),

    # -- MLOps --
    sk("skill.mlops_fundamentals", "MLOps Fundamentals", ["ML lifecycle management"],
       "mlops", "concept", "Practices for reliably operating ML systems in production."),
    sk("skill.experiment_tracking", "Experiment Tracking", ["MLflow", "Weights & Biases"],
       "mlops", "tool", "Logging and comparing ML experiment runs."),
    sk("skill.model_versioning", "Model Versioning", ["model registry"],
       "mlops", "concept", "Tracking and promoting trained model artifacts."),
    sk("skill.model_serving", "Model Serving & Deployment", ["inference API"],
       "mlops", "practice", "Exposing a trained model for online/offline inference."),
    sk("skill.ml_monitoring", "ML Model Monitoring", ["data drift", "model drift"],
       "mlops", "concept", "Detecting degradation of a deployed model over time."),
    sk("skill.data_pipelines", "Data Pipelines", ["ETL for ML", "feature pipelines"],
       "mlops", "concept", "Automated flows that prepare data for training/serving."),
    sk("skill.data_engineering_basics", "Data Engineering Basics", ["data ingestion"],
       "mlops", "concept", "Fundamentals of moving and transforming data at scale."),

    # -- data analysis --
    sk("skill.data_cleaning", "Data Cleaning & Wrangling", ["handling missing data"],
       "data_analysis", "practice", "Detecting and fixing data quality issues."),
    sk("skill.exploratory_data_analysis", "Exploratory Data Analysis", ["EDA"],
       "data_analysis", "practice", "Summarizing and visualizing data to find patterns."),
    sk("skill.excel", "Spreadsheet Analysis (Excel)", ["Excel", "pivot tables"],
       "data_analysis", "tool", "Analyzing tabular data with spreadsheets."),
    sk("skill.spreadsheet_formulas", "Advanced Spreadsheet Formulas", ["VLOOKUP", "XLOOKUP"],
       "data_analysis", "concept", "Formula-based computation and lookups in spreadsheets."),
    sk("skill.etl_fundamentals", "ETL Fundamentals", ["extract transform load"],
       "data_analysis", "concept", "Moving data between systems with transformation steps."),
    sk("skill.business_requirements_analysis", "Business Requirements Analysis", ["stakeholder requirements"],
       "data_analysis", "practice", "Translating a business question into an analysis plan."),
    sk("skill.kpi_metrics_design", "KPI & Metrics Design", ["metric definition"],
       "data_analysis", "practice", "Defining metrics that faithfully track a business goal."),
    sk("skill.data_governance", "Data Governance & Quality", ["data quality"],
       "data_analysis", "concept", "Policies and checks that keep data trustworthy."),
    sk("skill.data_ethics_privacy", "Data Ethics & Privacy", ["PII handling"],
       "data_analysis", "concept", "Handling data responsibly and respecting privacy."),
    sk("skill.communication_stakeholders", "Communicating Insights to Stakeholders", ["presenting analysis"],
       "data_analysis", "practice", "Presenting analytical findings to a non-technical audience."),

    # -- data visualization --
    sk("skill.data_visualization_fundamentals", "Data Visualization Fundamentals", ["chart design basics"],
       "data_visualization", "concept", "Choosing the right chart to communicate data clearly."),
    sk("skill.matplotlib_seaborn", "Matplotlib & Seaborn", ["matplotlib", "seaborn"],
       "data_visualization", "tool", "Plotting data in Python with matplotlib/seaborn."),
    sk("skill.tableau", "Tableau", ["Tableau"],
       "data_visualization", "tool", "Building interactive dashboards in Tableau."),
    sk("skill.powerbi", "Power BI", ["Power BI"],
       "data_visualization", "tool", "Building interactive dashboards in Power BI."),
    sk("skill.dashboarding", "Dashboard Design", ["BI dashboards"],
       "data_visualization", "practice", "Designing dashboards for ongoing monitoring."),
    sk("skill.data_storytelling", "Data Storytelling & Communication", ["narrative with data"],
       "data_visualization", "practice", "Framing data findings as a persuasive narrative."),

    # -- databases / SQL --
    sk("skill.sql_fundamentals", "SQL Fundamentals", ["SQL", "SELECT queries"],
       "databases_sql", "concept", "Querying relational data with SQL."),
    sk("skill.sql_joins", "SQL Joins", ["INNER JOIN", "LEFT JOIN"],
       "databases_sql", "concept", "Combining rows across tables with joins."),
    sk("skill.sql_aggregation", "SQL Aggregation & Grouping", ["GROUP BY", "aggregate functions"],
       "databases_sql", "concept", "Summarizing rows with GROUP BY and aggregate functions."),
    sk("skill.relational_modeling", "Relational Database Design", ["normalization", "ER modeling"],
       "databases_sql", "concept", "Designing normalized relational schemas."),
    sk("skill.indexing_query_optimization", "Indexing & Query Optimization", ["query plans"],
       "databases_sql", "concept", "Speeding up queries with indexes and plan analysis."),
    sk("skill.transactions_acid", "Transactions & ACID", ["ACID properties"],
       "databases_sql", "concept", "Guarantees relational transactions provide."),
    sk("skill.nosql_fundamentals", "NoSQL Fundamentals", ["document databases", "key-value stores"],
       "databases_sql", "concept", "Non-relational data models and when to use them."),
    sk("skill.postgresql", "PostgreSQL", ["Postgres"],
       "databases_sql", "tool", "Operating and querying a PostgreSQL database."),
    sk("skill.orm_usage", "ORM Usage", ["SQLAlchemy", "object-relational mapping"],
       "databases_sql", "tool", "Mapping objects to relational rows via an ORM."),
    sk("skill.database_migrations", "Database Migrations", ["schema migrations", "Alembic"],
       "databases_sql", "practice", "Evolving a schema safely over time."),

    # -- backend engineering --
    sk("skill.backend_fundamentals", "Backend Engineering Fundamentals", ["backend basics"],
       "backend_engineering", "concept", "Umbrella grouping of core backend-development skills.",
       assessable=False),
    sk("skill.http_fundamentals", "HTTP Fundamentals", ["HTTP protocol", "status codes"],
       "backend_engineering", "concept", "Request/response semantics of the HTTP protocol."),
    sk("skill.rest_api_design", "REST API Design", ["RESTful APIs"],
       "backend_engineering", "concept", "Designing resource-oriented HTTP APIs."),
    sk("skill.rest_vs_grpc", "RPC & gRPC Basics", ["gRPC"],
       "backend_engineering", "concept", "When and how to use RPC-style APIs vs REST."),
    sk("skill.graphql", "GraphQL", ["GraphQL"],
       "backend_engineering", "tool", "Query-driven APIs with GraphQL."),
    sk("skill.backend_framework", "Backend Web Framework", ["FastAPI", "Express.js", "Flask", "Django"],
       "backend_engineering", "tool", "Building HTTP services with a backend framework."),
    sk("skill.authentication_authorization", "Authentication & Authorization", ["OAuth", "JWT"],
       "backend_engineering", "concept", "Verifying identity and enforcing access control."),
    sk("skill.caching", "Caching Strategies", ["Redis caching", "cache invalidation"],
       "backend_engineering", "concept", "Speeding up systems by caching computed/fetched data."),
    sk("skill.message_queues", "Message Queues", ["RabbitMQ", "Kafka basics"],
       "backend_engineering", "concept", "Asynchronous communication between services."),
    sk("skill.microservices", "Microservices Architecture", ["service decomposition"],
       "backend_engineering", "concept", "Decomposing a system into independently deployable services."),
    sk("skill.system_design_fundamentals", "System Design Fundamentals", ["scalability basics"],
       "backend_engineering", "concept", "Designing systems that scale and stay reliable."),
    sk("skill.load_balancing", "Load Balancing", ["load balancers"],
       "backend_engineering", "concept", "Distributing traffic across multiple instances."),
    sk("skill.api_testing", "API Testing", ["integration testing for APIs", "Postman"],
       "backend_engineering", "practice", "Verifying API behavior with automated tests."),
    sk("skill.websockets", "WebSockets & Real-Time Communication", ["websockets"],
       "backend_engineering", "concept", "Bidirectional, persistent client-server communication."),
    sk("skill.api_documentation", "API Documentation (OpenAPI/Swagger)", ["OpenAPI", "Swagger"],
       "backend_engineering", "practice", "Documenting an API in a machine-readable spec."),
    sk("skill.rate_limiting", "API Rate Limiting & Throttling", ["rate limiting"],
       "backend_engineering", "concept", "Protecting a service from excess/abusive traffic."),
    sk("skill.idempotency", "Idempotency in APIs", ["idempotent requests"],
       "backend_engineering", "concept", "Designing requests safe to retry without side effects."),
    sk("skill.env_config_management", "Configuration & Secrets Management", ["env vars", "secrets"],
       "backend_engineering", "concept", "Managing environment-specific config and secrets safely."),

    # -- devops / infrastructure --
    sk("skill.docker", "Docker & Containerization", ["Docker", "containers"],
       "devops_infrastructure", "tool", "Packaging and running applications in containers."),
    sk("skill.kubernetes_basics", "Kubernetes Basics", ["K8s"],
       "devops_infrastructure", "concept", "Orchestrating containers at scale with Kubernetes."),
    sk("skill.ci_cd", "CI/CD Pipelines", ["continuous integration", "continuous deployment"],
       "devops_infrastructure", "practice", "Automating build, test and deployment pipelines."),
    sk("skill.cloud_fundamentals", "Cloud Computing Fundamentals", ["AWS basics", "cloud services"],
       "devops_infrastructure", "concept", "Core concepts of public cloud platforms."),
    sk("skill.cost_estimation_cloud", "Cloud Cost Awareness", ["cloud billing"],
       "devops_infrastructure", "concept", "Estimating and controlling cloud infrastructure cost."),
    sk("skill.infrastructure_as_code", "Infrastructure as Code", ["Terraform basics"],
       "devops_infrastructure", "concept", "Defining infrastructure declaratively as versioned code."),
    sk("skill.logging_monitoring", "Logging & Monitoring", ["observability basics"],
       "devops_infrastructure", "concept", "Instrumenting systems to observe health and behavior."),

    # -- security --
    sk("skill.security_fundamentals", "Application Security Fundamentals", ["secure coding basics"],
       "security", "concept", "Core principles of building secure applications."),
    sk("skill.web_security_owasp", "Web Security (OWASP)", ["SQL injection", "XSS", "CSRF"],
       "security", "concept", "Common web vulnerabilities and how to prevent them."),
]

SKILL_IDS = {s["skill_id"] for s in SKILLS}


# --------------------------------------------------------------------------
# 2. ROLES
# --------------------------------------------------------------------------

ROLES = [
    role(
        "role.ml_engineer", "Machine Learning Engineer",
        "Builds, trains, evaluates and deploys machine learning models, from classical "
        "ML through deep learning, with production-grade MLOps practices.",
        [
            ("skill.python", 2, 3), ("skill.numpy", 2, 2), ("skill.pandas", 2, 2),
            ("skill.algebra_basics", 1, 2), ("skill.derivatives", 1, 2), ("skill.chain_rule", 2, 3),
            ("skill.multivariable_calculus", 1, 2), ("skill.linear_algebra_vectors", 1, 2),
            ("skill.linear_algebra_matrices", 2, 3), ("skill.probability_fundamentals", 2, 2),
            ("skill.descriptive_statistics", 1, 1), ("skill.probability_distributions", 1, 1),
            ("skill.ml_fundamentals", 2, 3), ("skill.supervised_learning", 2, 3),
            ("skill.unsupervised_learning", 1, 1), ("skill.model_evaluation", 2, 2),
            ("skill.overfitting_regularization", 2, 2), ("skill.feature_engineering", 2, 2),
            ("skill.cross_validation", 1, 1), ("skill.decision_trees_ensembles", 2, 2),
            ("skill.scikit_learn", 2, 2), ("skill.neural_network_fundamentals", 2, 3),
            ("skill.backpropagation", 2, 3), ("skill.activation_functions", 1, 1),
            ("skill.loss_functions", 2, 2), ("skill.training_neural_networks", 2, 3),
            ("skill.pytorch", 2, 3), ("skill.cnn", 2, 2), ("skill.rnn_sequence_models", 1, 1),
            ("skill.transformers_attention", 1, 1), ("skill.transfer_learning", 1, 1),
            ("skill.regularization_dl", 1, 1), ("skill.opencv", 1, 1), ("skill.object_detection", 1, 1),
            ("skill.nlp_fundamentals", 1, 1), ("skill.llm_basics", 1, 1),
            ("skill.experiment_tracking", 1, 2), ("skill.model_versioning", 1, 1),
            ("skill.model_serving", 1, 2), ("skill.ml_monitoring", 1, 1),
            ("skill.mlops_fundamentals", 1, 2), ("skill.docker", 1, 2),
            ("skill.cloud_fundamentals", 1, 1), ("skill.git", 1, 2),
            ("skill.sql_fundamentals", 1, 1), ("skill.data_cleaning", 2, 2),
            ("skill.hyperparameter_tuning", 1, 1),
        ],
    ),
    role(
        "role.data_analyst", "Data Analyst",
        "Turns raw business data into decisions: cleaning, analyzing, visualizing and "
        "communicating findings to stakeholders.",
        [
            ("skill.excel", 2, 3), ("skill.sql_fundamentals", 2, 3), ("skill.sql_joins", 2, 3),
            ("skill.sql_aggregation", 2, 2), ("skill.descriptive_statistics", 2, 3),
            ("skill.probability_fundamentals", 1, 1), ("skill.probability_distributions", 1, 1),
            ("skill.inferential_statistics", 1, 2), ("skill.hypothesis_testing", 1, 2),
            ("skill.regression_analysis", 1, 2), ("skill.ab_testing", 1, 1),
            ("skill.data_cleaning", 2, 3), ("skill.exploratory_data_analysis", 2, 3),
            ("skill.python", 1, 2), ("skill.pandas", 1, 2), ("skill.numpy", 1, 1),
            ("skill.data_visualization_fundamentals", 2, 3), ("skill.matplotlib_seaborn", 1, 1),
            ("skill.tableau", 2, 2), ("skill.powerbi", 1, 1), ("skill.dashboarding", 2, 2),
            ("skill.data_storytelling", 2, 3), ("skill.etl_fundamentals", 1, 1),
            ("skill.business_requirements_analysis", 2, 2), ("skill.kpi_metrics_design", 1, 2),
            ("skill.data_governance", 1, 1), ("skill.communication_stakeholders", 2, 2),
            ("skill.spreadsheet_formulas", 2, 2), ("skill.time_series_analysis", 1, 1),
            ("skill.git", 1, 1),
        ],
    ),
    role(
        "role.backend_developer", "Backend Developer",
        "Designs, builds and operates server-side systems and APIs: data modeling, "
        "service design, security and deployment.",
        [
            ("skill.python", 2, 2), ("skill.programming_fundamentals", 2, 3),
            ("skill.control_flow", 1, 2), ("skill.functions_modularity", 1, 2),
            ("skill.oop", 2, 3), ("skill.error_handling", 1, 2), ("skill.testing_fundamentals", 2, 3),
            ("skill.unit_testing_python", 2, 2), ("skill.debugging", 1, 2),
            ("skill.dsa_arrays_strings", 1, 1), ("skill.dsa_hashing", 1, 1), ("skill.big_o", 1, 2),
            ("skill.recursion", 1, 1), ("skill.dsa_trees", 1, 1), ("skill.dsa_graphs", 1, 1),
            ("skill.sql_fundamentals", 2, 3), ("skill.sql_joins", 2, 2),
            ("skill.relational_modeling", 2, 3), ("skill.indexing_query_optimization", 1, 2),
            ("skill.transactions_acid", 1, 2), ("skill.nosql_fundamentals", 1, 1),
            ("skill.postgresql", 1, 1), ("skill.orm_usage", 1, 1), ("skill.database_migrations", 1, 1),
            ("skill.rest_api_design", 2, 3), ("skill.http_fundamentals", 2, 3),
            ("skill.backend_framework", 2, 3), ("skill.authentication_authorization", 2, 3),
            ("skill.caching", 1, 2), ("skill.message_queues", 1, 1), ("skill.microservices", 1, 1),
            ("skill.system_design_fundamentals", 1, 2), ("skill.load_balancing", 1, 1),
            ("skill.api_testing", 1, 2), ("skill.websockets", 1, 1), ("skill.docker", 2, 3),
            ("skill.ci_cd", 1, 2), ("skill.cloud_fundamentals", 1, 2), ("skill.logging_monitoring", 1, 1),
            ("skill.security_fundamentals", 1, 2), ("skill.web_security_owasp", 2, 3),
            ("skill.git", 2, 3), ("skill.github_workflow", 1, 1), ("skill.cli_basics", 1, 1),
            ("skill.linux_fundamentals", 1, 1), ("skill.async_programming", 1, 1),
            ("skill.design_patterns", 1, 1), ("skill.code_review_practice", 1, 1),
            ("skill.env_config_management", 1, 1), ("skill.api_documentation", 1, 1),
        ],
    ),
]

ROLE_IDS = {r["role_id"] for r in ROLES}


# --------------------------------------------------------------------------
# 3. PREREQUISITE / PART_OF / RELATED_TO GRAPH  (Skill -> Skill edges only;
#    REQUIRES/TARGETS/ASSESSES/MISCONCEPTION_OF/ROOTED_IN/REMEDIATED_BY live
#    in roles.json / resources.json / assessment_items.json / misconceptions.json)
# --------------------------------------------------------------------------

H, SOFT = "hard", "soft"

PREREQ_EDGES = [
    # math
    ("skill.algebra_basics", "skill.functions_graphs_math", H),
    ("skill.functions_graphs_math", "skill.calculus_limits", H),
    ("skill.calculus_limits", "skill.derivatives", H),
    ("skill.derivatives", "skill.chain_rule", H),
    ("skill.derivatives", "skill.integrals", SOFT),
    ("skill.chain_rule", "skill.multivariable_calculus", H),
    ("skill.algebra_basics", "skill.linear_algebra_vectors", H),
    ("skill.linear_algebra_vectors", "skill.linear_algebra_matrices", H),
    ("skill.linear_algebra_matrices", "skill.eigenvalues_eigenvectors", H),
    ("skill.multivariable_calculus", "skill.optimization_basics", H),
    ("skill.linear_algebra_matrices", "skill.optimization_basics", H),
    # probability / stats
    ("skill.algebra_basics", "skill.probability_fundamentals", SOFT),
    ("skill.probability_fundamentals", "skill.probability_distributions", H),
    ("skill.probability_distributions", "skill.inferential_statistics", H),
    ("skill.descriptive_statistics", "skill.inferential_statistics", H),
    ("skill.inferential_statistics", "skill.hypothesis_testing", H),
    ("skill.hypothesis_testing", "skill.ab_testing", H),
    ("skill.probability_fundamentals", "skill.bayesian_thinking", SOFT),
    ("skill.descriptive_statistics", "skill.regression_analysis", H),
    ("skill.probability_distributions", "skill.regression_analysis", SOFT),
    ("skill.descriptive_statistics", "skill.time_series_analysis", H),
    ("skill.regression_analysis", "skill.time_series_analysis", SOFT),
    # programming fundamentals
    ("skill.programming_fundamentals", "skill.control_flow", H),
    ("skill.control_flow", "skill.functions_modularity", H),
    ("skill.functions_modularity", "skill.oop", H),
    ("skill.functions_modularity", "skill.error_handling", H),
    ("skill.oop", "skill.design_patterns", SOFT),
    ("skill.functions_modularity", "skill.recursion", H),
    ("skill.programming_fundamentals", "skill.debugging", SOFT),
    ("skill.error_handling", "skill.testing_fundamentals", H),
    ("skill.programming_fundamentals", "skill.json_data_formats", SOFT),
    # python
    ("skill.python", "skill.python_data_structures", H),
    ("skill.python", "skill.python_oop", H),
    ("skill.oop", "skill.python_oop", H),
    ("skill.python", "skill.python_venv_packaging", SOFT),
    ("skill.python", "skill.regex", SOFT),
    ("skill.python", "skill.async_programming", H),
    ("skill.python", "skill.web_scraping", SOFT),
    ("skill.python", "skill.unit_testing_python", H),
    ("skill.testing_fundamentals", "skill.unit_testing_python", H),
    ("skill.python_data_structures", "skill.numpy", H),
    ("skill.numpy", "skill.pandas", H),
    # DSA
    ("skill.python_data_structures", "skill.dsa_arrays_strings", H),
    ("skill.dsa_arrays_strings", "skill.dsa_linked_lists", H),
    ("skill.dsa_linked_lists", "skill.dsa_stacks_queues", H),
    ("skill.dsa_arrays_strings", "skill.dsa_hashing", H),
    ("skill.recursion", "skill.dsa_trees", H),
    ("skill.dsa_trees", "skill.dsa_graphs", H),
    ("skill.dsa_arrays_strings", "skill.dsa_sorting_searching", H),
    ("skill.dsa_sorting_searching", "skill.big_o", H),
    ("skill.dsa_trees", "skill.big_o", SOFT),
    # ML fundamentals
    ("skill.python", "skill.ml_fundamentals", H),
    ("skill.pandas", "skill.ml_fundamentals", SOFT),
    ("skill.descriptive_statistics", "skill.ml_fundamentals", H),
    ("skill.linear_algebra_matrices", "skill.ml_fundamentals", SOFT),
    ("skill.ml_fundamentals", "skill.supervised_learning", H),
    ("skill.ml_fundamentals", "skill.unsupervised_learning", H),
    ("skill.unsupervised_learning", "skill.clustering", H),
    ("skill.unsupervised_learning", "skill.dimensionality_reduction", H),
    ("skill.supervised_learning", "skill.model_evaluation", H),
    ("skill.supervised_learning", "skill.overfitting_regularization", H),
    ("skill.overfitting_regularization", "skill.cross_validation", H),
    ("skill.supervised_learning", "skill.feature_engineering", H),
    ("skill.supervised_learning", "skill.decision_trees_ensembles", H),
    ("skill.python", "skill.scikit_learn", H),
    ("skill.supervised_learning", "skill.scikit_learn", SOFT),
    ("skill.supervised_learning", "skill.hyperparameter_tuning", H),
    ("skill.model_evaluation", "skill.model_interpretability", SOFT),
    # deep learning (demo chain)
    ("skill.optimization_basics", "skill.neural_network_fundamentals", H),
    ("skill.overfitting_regularization", "skill.neural_network_fundamentals", SOFT),
    ("skill.neural_network_fundamentals", "skill.activation_functions", H),
    ("skill.neural_network_fundamentals", "skill.loss_functions", H),
    ("skill.chain_rule", "skill.backpropagation", H),                       # demo edge
    ("skill.neural_network_fundamentals", "skill.backpropagation", H),
    ("skill.activation_functions", "skill.backpropagation", H),
    ("skill.optimization_basics", "skill.gradient_descent_variants", H),
    ("skill.python", "skill.pytorch", H),
    ("skill.python", "skill.tensorflow_keras", H),
    ("skill.neural_network_fundamentals", "skill.tensorflow_keras", SOFT),
    ("skill.pytorch", "skill.training_neural_networks", H),
    ("skill.backpropagation", "skill.training_neural_networks", H),         # demo edge
    ("skill.loss_functions", "skill.training_neural_networks", H),
    ("skill.gradient_descent_variants", "skill.training_neural_networks", H),
    ("skill.training_neural_networks", "skill.batch_normalization", SOFT),
    ("skill.training_neural_networks", "skill.regularization_dl", H),
    ("skill.training_neural_networks", "skill.cnn", H),
    ("skill.training_neural_networks", "skill.rnn_sequence_models", H),
    ("skill.rnn_sequence_models", "skill.transformers_attention", H),
    ("skill.transformers_attention", "skill.llm_basics", H),
    ("skill.llm_basics", "skill.prompt_engineering", H),
    ("skill.llm_basics", "skill.huggingface", SOFT),
    ("skill.python", "skill.huggingface", H),
    ("skill.cnn", "skill.transfer_learning", H),
    # computer vision
    ("skill.image_processing_basics", "skill.opencv", H),
    ("skill.opencv", "skill.cnn_image_classification", H),
    ("skill.cnn", "skill.cnn_image_classification", H),
    ("skill.cnn_image_classification", "skill.object_detection", H),
    ("skill.object_detection", "skill.image_segmentation", SOFT),
    # NLP
    ("skill.python", "skill.nlp_fundamentals", H),
    ("skill.nlp_fundamentals", "skill.word_embeddings", H),
    ("skill.word_embeddings", "skill.transformers_attention", SOFT),
    # MLOps
    ("skill.git", "skill.experiment_tracking", SOFT),
    ("skill.training_neural_networks", "skill.experiment_tracking", H),
    ("skill.experiment_tracking", "skill.model_versioning", H),
    ("skill.docker", "skill.model_serving", H),
    ("skill.model_versioning", "skill.model_serving", H),
    ("skill.model_serving", "skill.ml_monitoring", H),
    ("skill.model_serving", "skill.mlops_fundamentals", SOFT),
    ("skill.data_cleaning", "skill.data_pipelines", H),
    ("skill.data_pipelines", "skill.mlops_fundamentals", SOFT),
    ("skill.etl_fundamentals", "skill.data_engineering_basics", SOFT),
    # data analysis
    ("skill.pandas", "skill.exploratory_data_analysis", H),
    ("skill.excel", "skill.exploratory_data_analysis", SOFT),
    ("skill.data_cleaning", "skill.exploratory_data_analysis", H),
    ("skill.sql_fundamentals", "skill.data_cleaning", SOFT),
    ("skill.exploratory_data_analysis", "skill.data_visualization_fundamentals", H),
    ("skill.data_visualization_fundamentals", "skill.matplotlib_seaborn", H),
    ("skill.data_visualization_fundamentals", "skill.tableau", H),
    ("skill.data_visualization_fundamentals", "skill.powerbi", H),
    ("skill.tableau", "skill.dashboarding", H),
    ("skill.powerbi", "skill.dashboarding", SOFT),
    ("skill.dashboarding", "skill.data_storytelling", H),
    ("skill.data_storytelling", "skill.communication_stakeholders", H),
    ("skill.business_requirements_analysis", "skill.kpi_metrics_design", H),
    ("skill.kpi_metrics_design", "skill.data_governance", SOFT),
    ("skill.data_governance", "skill.data_ethics_privacy", SOFT),
    ("skill.excel", "skill.spreadsheet_formulas", H),
    ("skill.sql_fundamentals", "skill.etl_fundamentals", H),
    # SQL / DB
    ("skill.sql_fundamentals", "skill.sql_joins", H),
    ("skill.sql_joins", "skill.sql_aggregation", H),
    ("skill.sql_fundamentals", "skill.relational_modeling", H),
    ("skill.relational_modeling", "skill.indexing_query_optimization", H),
    ("skill.relational_modeling", "skill.transactions_acid", H),
    ("skill.sql_fundamentals", "skill.nosql_fundamentals", SOFT),
    ("skill.relational_modeling", "skill.postgresql", H),
    ("skill.postgresql", "skill.orm_usage", H),
    ("skill.orm_usage", "skill.database_migrations", H),
    # backend
    ("skill.http_fundamentals", "skill.rest_api_design", H),
    ("skill.oop", "skill.rest_api_design", SOFT),
    ("skill.rest_api_design", "skill.backend_framework", H),
    ("skill.python", "skill.backend_framework", H),
    ("skill.backend_framework", "skill.security_fundamentals", H),
    ("skill.security_fundamentals", "skill.authentication_authorization", H),
    ("skill.security_fundamentals", "skill.web_security_owasp", H),
    ("skill.backend_framework", "skill.caching", H),
    ("skill.backend_framework", "skill.message_queues", SOFT),
    ("skill.rest_api_design", "skill.microservices", H),
    ("skill.microservices", "skill.system_design_fundamentals", H),
    ("skill.system_design_fundamentals", "skill.load_balancing", H),
    ("skill.rest_api_design", "skill.api_testing", H),
    ("skill.testing_fundamentals", "skill.api_testing", H),
    ("skill.rest_api_design", "skill.websockets", SOFT),
    ("skill.rest_api_design", "skill.graphql", SOFT),
    ("skill.rest_api_design", "skill.api_documentation", H),
    ("skill.backend_framework", "skill.rate_limiting", SOFT),
    ("skill.backend_framework", "skill.idempotency", SOFT),
    ("skill.backend_framework", "skill.env_config_management", SOFT),
    ("skill.rest_api_design", "skill.rest_vs_grpc", SOFT),
    ("skill.json_data_formats", "skill.rest_api_design", SOFT),
    # devops
    ("skill.cli_basics", "skill.linux_fundamentals", H),
    ("skill.linux_fundamentals", "skill.docker", H),
    ("skill.docker", "skill.kubernetes_basics", H),
    ("skill.git", "skill.ci_cd", H),
    ("skill.testing_fundamentals", "skill.ci_cd", H),
    ("skill.docker", "skill.ci_cd", H),
    ("skill.ci_cd", "skill.cloud_fundamentals", SOFT),
    ("skill.cloud_fundamentals", "skill.infrastructure_as_code", H),
    ("skill.cloud_fundamentals", "skill.cost_estimation_cloud", SOFT),
    ("skill.backend_framework", "skill.logging_monitoring", SOFT),
    # tools / collab
    ("skill.cli_basics", "skill.git", H),
    ("skill.git", "skill.github_workflow", H),
    ("skill.github_workflow", "skill.code_review_practice", H),
    ("skill.code_review_practice", "skill.agile_practices", SOFT),
    ("skill.functions_modularity", "skill.documentation_practice", SOFT),
    ("skill.git", "skill.version_control_branching", H),
]

PART_OF_EDGES = [
    ("skill.chain_rule", "skill.math_for_ml"),
    ("skill.derivatives", "skill.math_for_ml"),
    ("skill.linear_algebra_matrices", "skill.math_for_ml"),
    ("skill.multivariable_calculus", "skill.math_for_ml"),
    ("skill.optimization_basics", "skill.math_for_ml"),
    ("skill.descriptive_statistics", "skill.statistics_for_data_analysis"),
    ("skill.inferential_statistics", "skill.statistics_for_data_analysis"),
    ("skill.hypothesis_testing", "skill.statistics_for_data_analysis"),
    ("skill.regression_analysis", "skill.statistics_for_data_analysis"),
    ("skill.neural_network_fundamentals", "skill.deep_learning_fundamentals"),
    ("skill.backpropagation", "skill.deep_learning_fundamentals"),
    ("skill.cnn", "skill.deep_learning_fundamentals"),
    ("skill.rnn_sequence_models", "skill.deep_learning_fundamentals"),
    ("skill.transformers_attention", "skill.deep_learning_fundamentals"),
    ("skill.opencv", "skill.computer_vision_fundamentals"),
    ("skill.object_detection", "skill.computer_vision_fundamentals"),
    ("skill.image_segmentation", "skill.computer_vision_fundamentals"),
    ("skill.nlp_fundamentals", "skill.nlp_and_llms"),
    ("skill.word_embeddings", "skill.nlp_and_llms"),
    ("skill.llm_basics", "skill.nlp_and_llms"),
    ("skill.rest_api_design", "skill.backend_fundamentals"),
    ("skill.authentication_authorization", "skill.backend_fundamentals"),
    ("skill.microservices", "skill.backend_fundamentals"),
]

RELATED_TO_EDGES = [
    ("skill.pandas", "skill.excel", 0.4),
    ("skill.tableau", "skill.powerbi", 0.6),
    ("skill.pytorch", "skill.tensorflow_keras", 0.7),
    ("skill.sql_fundamentals", "skill.nosql_fundamentals", 0.3),
    ("skill.cnn", "skill.rnn_sequence_models", 0.3),
]

SKILL_EDGES = (
    [edge(a, b, "PREREQUISITE_OF", strength=s) for a, b, s in PREREQ_EDGES]
    + [edge(a, b, "PART_OF") for a, b in PART_OF_EDGES]
    + [edge(a, b, "RELATED_TO", weight=w) for a, b, w in RELATED_TO_EDGES]
)


# --------------------------------------------------------------------------
# 4. RESOURCE CATALOG (~100-150 target). Real URLs only, from reputable
#    official/educational sources. curation_tier="curated" = team-reviewed
#    for difficulty/skill_targets/prerequisites per design §15.2.
# --------------------------------------------------------------------------

RESOURCES = [
    # -- math foundations --
    res("res.khan_algebra", "Algebra Basics", "https://www.khanacademy.org/math/algebra-basics",
        "Khan Academy", "course", [("skill.algebra_basics", 0, 1)], 1, 300, "do", [],
        "Refresh core algebra skills needed for calculus and ML math.", "en", "free", "curated"),
    res("res.khan_diff_calc", "Differential Calculus", "https://www.khanacademy.org/math/differential-calculus",
        "Khan Academy", "course",
        [("skill.calculus_limits", 0, 1), ("skill.derivatives", 0, 1), ("skill.chain_rule", 0, 1)],
        1, 360, "do", ["skill.algebra_basics"],
        "Build limits, derivative and chain-rule fundamentals from the ground up.", "en", "free", "curated"),
    res("res.3b1b_calculus", "Essence of Calculus", "https://www.3blue1brown.com/topics/calculus",
        "3Blue1Brown", "video", [("skill.derivatives", 1, 2), ("skill.chain_rule", 1, 2)],
        2, 190, "watch", ["skill.algebra_basics"],
        "Build visual intuition for derivatives and the chain rule.", "en", "free", "curated"),
    res("res.khan_integrals", "Integral Calculus", "https://www.khanacademy.org/math/integral-calculus",
        "Khan Academy", "course", [("skill.integrals", 0, 1)], 1, 240, "do", ["skill.derivatives"],
        "Learn antiderivatives and accumulation.", "en", "free", "curated"),
    res("res.khan_multivar_calc", "Multivariable Calculus", "https://www.khanacademy.org/math/multivariable-calculus",
        "Khan Academy", "course", [("skill.multivariable_calculus", 0, 1)], 2, 300, "do", ["skill.chain_rule"],
        "Partial derivatives and gradients for functions of several variables.", "en", "free", "curated"),
    res("res.3b1b_linalg", "Essence of Linear Algebra", "https://www.3blue1brown.com/topics/linear-algebra",
        "3Blue1Brown", "video", [("skill.linear_algebra_vectors", 1, 2), ("skill.linear_algebra_matrices", 1, 2)],
        2, 180, "watch", ["skill.algebra_basics"],
        "Visual intuition for vectors, matrices and linear transformations.", "en", "free", "curated"),
    res("res.khan_linalg", "Linear Algebra", "https://www.khanacademy.org/math/linear-algebra",
        "Khan Academy", "course", [("skill.linear_algebra_vectors", 0, 1), ("skill.linear_algebra_matrices", 0, 1)],
        1, 360, "do", ["skill.algebra_basics"],
        "Vector and matrix operations from first principles.", "en", "free", "curated"),
    res("res.khan_eigen", "Eigenvalues and Eigenvectors (Linear Algebra course)",
        "https://www.khanacademy.org/math/linear-algebra",
        "Khan Academy", "course", [("skill.eigenvalues_eigenvectors", 1, 2)], 2, 90, "do",
        ["skill.linear_algebra_matrices"], "Compute and interpret eigenvalues/eigenvectors.", "en", "free", "curated"),
    res("res.mlcc_gradient_descent", "Reducing Loss: Gradient Descent",
        "https://developers.google.com/machine-learning/crash-course/reducing-loss/gradient-descent",
        "Google", "article", [("skill.optimization_basics", 1, 2)], 2, 30, "read", ["skill.derivatives"],
        "How gradient descent minimizes a loss function step by step.", "en", "free", "curated"),

    # -- probability & statistics --
    res("res.khan_stats", "Statistics and Probability", "https://www.khanacademy.org/math/statistics-probability",
        "Khan Academy", "course", [("skill.probability_fundamentals", 0, 1), ("skill.descriptive_statistics", 0, 1)],
        1, 360, "do", [], "Core probability and descriptive statistics.", "en", "free", "curated"),
    res("res.khan_dists", "Random Variables & Probability Distributions (Statistics course)",
        "https://www.khanacademy.org/math/statistics-probability",
        "Khan Academy", "course", [("skill.probability_distributions", 0, 2)], 2, 240, "do",
        ["skill.probability_fundamentals"], "Discrete and continuous distributions, expectation, variance.",
        "en", "free", "curated"),
    res("res.khan_inference", "Significance Tests / Hypothesis Testing (Statistics course)",
        "https://www.khanacademy.org/math/statistics-probability",
        "Khan Academy", "course", [("skill.hypothesis_testing", 1, 2), ("skill.inferential_statistics", 1, 2)],
        2, 240, "do", ["skill.probability_distributions", "skill.descriptive_statistics"],
        "Formulate and test statistical hypotheses correctly.", "en", "free", "curated"),
    res("res.khan_confidence", "Confidence Intervals (Statistics course)",
        "https://www.khanacademy.org/math/statistics-probability",
        "Khan Academy", "course", [("skill.inferential_statistics", 1, 2)], 2, 150, "do",
        ["skill.probability_distributions"], "Constructing and correctly interpreting confidence intervals.",
        "en", "free", "curated"),
    res("res.khan_regression", "Regression (Statistics course)",
        "https://www.khanacademy.org/math/statistics-probability",
        "Khan Academy", "course", [("skill.regression_analysis", 1, 2)], 2, 180, "do",
        ["skill.descriptive_statistics"], "Modeling linear relationships between two variables.", "en", "free",
        "curated"),
    res("res.khan_bayes", "Bayes Theorem (Statistics course)", "https://www.khanacademy.org/math/statistics-probability",
        "Khan Academy", "course", [("skill.bayesian_thinking", 1, 2)], 2, 45, "read",
        ["skill.probability_fundamentals"], "Conditional probability and Bayes' theorem.", "en", "free", "community"),
    res("res.optimizely_ab", "A/B Testing Guide", "https://www.optimizely.com/optimization-glossary/ab-testing/",
        "Optimizely", "article", [("skill.ab_testing", 1, 2)], 2, 25, "read", ["skill.hypothesis_testing"],
        "How to design and interpret an A/B test.", "en", "free", "community"),

    # -- programming fundamentals / python --
    res("res.py_tutorial", "The Python Tutorial", "https://docs.python.org/3/tutorial/",
        "Python Software Foundation", "docs", [("skill.python", 0, 2), ("skill.programming_fundamentals", 0, 1)],
        1, 360, "do", [], "Official start-to-finish tour of the Python language.", "en", "free", "curated"),
    res("res.py_datastructures", "Data Structures (Python docs)",
        "https://docs.python.org/3/tutorial/datastructures.html", "Python Software Foundation", "docs",
        [("skill.python_data_structures", 0, 2)], 1, 60, "read", ["skill.python"],
        "Lists, dicts, tuples, sets and comprehensions in Python.", "en", "free", "curated"),
    res("res.py_classes", "Classes (Python docs)", "https://docs.python.org/3/tutorial/classes.html",
        "Python Software Foundation", "docs", [("skill.python_oop", 0, 2), ("skill.oop", 0, 2)], 2, 60, "read",
        ["skill.python"], "Python's object model: classes, inheritance, dunder methods.", "en", "free", "curated"),
    res("res.py_errors", "Errors and Exceptions", "https://docs.python.org/3/tutorial/errors.html",
        "Python Software Foundation", "docs", [("skill.error_handling", 0, 1)], 1, 30, "read",
        ["skill.control_flow"], "Raising, catching and handling exceptions in Python.", "en", "free", "curated"),
    res("res.realpython_venv", "Python Virtual Environments: A Primer",
        "https://realpython.com/python-virtual-environments-a-primer/", "Real Python", "article",
        [("skill.python_venv_packaging", 0, 1)], 1, 25, "read", ["skill.python"],
        "Isolating project dependencies with venv/pip.", "en", "free", "curated"),
    res("res.pytest_docs", "pytest: Get Started", "https://docs.pytest.org/en/stable/getting-started.html",
        "pytest", "docs", [("skill.unit_testing_python", 0, 1), ("skill.testing_fundamentals", 0, 1)], 1, 45,
        "do", ["skill.python"], "Writing and running your first pytest tests.", "en", "free", "curated"),
    res("res.py_regex", "Regular Expression HOWTO", "https://docs.python.org/3/howto/regex.html",
        "Python Software Foundation", "docs", [("skill.regex", 0, 1)], 2, 40, "read", ["skill.python"],
        "Pattern matching with Python's re module.", "en", "free", "curated"),
    res("res.realpython_scraping", "Beautiful Soup: Build a Web Scraper",
        "https://realpython.com/beautiful-soup-web-scraper-python/", "Real Python", "article",
        [("skill.web_scraping", 0, 1)], 2, 45, "do", ["skill.python"],
        "Scraping and parsing web pages with requests + BeautifulSoup.", "en", "free", "community"),
    res("res.rp_asyncio", "Async IO in Python: A Complete Walkthrough",
        "https://realpython.com/async-io-python/", "Real Python", "article",
        [("skill.async_programming", 1, 2)], 3, 45, "read", ["skill.python"],
        "Concurrency with async/await and asyncio.", "en", "free", "curated"),
    res("res.freecodecamp_dsa", "Data Structures and Algorithms Course",
        "https://www.freecodecamp.org/news/learn-data-structures-and-algorithms/", "freeCodeCamp", "course",
        [("skill.dsa_arrays_strings", 0, 2), ("skill.dsa_sorting_searching", 0, 2)], 2, 480, "do",
        ["skill.python"], "Hands-on tour of core data structures and algorithms.", "en", "free", "community"),
    res("res.cs_bigo", "Big-O Cheat Sheet", "https://www.bigocheatsheet.com/",
        "BigOCheatSheet", "article", [("skill.big_o", 0, 1)], 1, 30, "read", [],
        "Reference for time/space complexity of common algorithms and structures.", "en", "free", "community"),
    res("res.gfg_recursion", "Recursion in Python", "https://www.geeksforgeeks.org/recursion-in-python/",
        "GeeksforGeeks", "article", [("skill.recursion", 0, 1)], 1, 30, "read", ["skill.functions_modularity"],
        "Base cases, call stacks and classic recursive patterns.", "en", "free", "community"),
    res("res.gfg_trees", "Introduction to Tree Data Structure",
        "https://www.geeksforgeeks.org/introduction-to-tree-data-structure/", "GeeksforGeeks", "article",
        [("skill.dsa_trees", 0, 2)], 2, 40, "read", ["skill.recursion"],
        "Binary trees, BSTs and traversal orders.", "en", "free", "community"),
    res("res.gfg_graphs", "Graph Data Structure and Algorithms",
        "https://www.geeksforgeeks.org/graph-data-structure-and-algorithms/", "GeeksforGeeks", "article",
        [("skill.dsa_graphs", 0, 2)], 2, 60, "read", ["skill.dsa_trees"],
        "Graph representations and BFS/DFS traversal.", "en", "free", "community"),
    res("res.gfg_hashing", "Hashing", "https://www.geeksforgeeks.org/hashing-data-structure/",
        "GeeksforGeeks", "article", [("skill.dsa_hashing", 0, 1)], 1, 25, "read", ["skill.dsa_arrays_strings"],
        "Hash tables, collisions and average-case lookup cost.", "en", "free", "community"),
    res("res.refactoring_patterns", "Design Patterns Catalog", "https://refactoring.guru/design-patterns/catalog",
        "Refactoring.Guru", "article", [("skill.design_patterns", 1, 2)], 2, 90, "read", ["skill.oop"],
        "Overview of classic object-oriented design patterns.", "en", "free", "curated"),

    # -- numpy / pandas / viz --
    res("res.numpy_quickstart", "NumPy Quickstart", "https://numpy.org/doc/stable/user/quickstart.html",
        "NumPy", "docs", [("skill.numpy", 0, 2)], 1, 60, "do", ["skill.python_data_structures"],
        "Arrays, broadcasting and vectorized operations in NumPy.", "en", "free", "curated"),
    res("res.pandas_10min", "10 Minutes to pandas", "https://pandas.pydata.org/docs/user_guide/10min.html",
        "pandas", "docs", [("skill.pandas", 0, 2)], 1, 40, "do", ["skill.numpy"],
        "A fast tour of pandas DataFrame/Series basics.", "en", "free", "curated"),
    res("res.matplotlib_pyplot", "Pyplot Tutorial", "https://matplotlib.org/stable/tutorials/pyplot.html",
        "Matplotlib", "docs", [("skill.matplotlib_seaborn", 0, 1)], 1, 40, "do", ["skill.numpy"],
        "Plotting basics with matplotlib's pyplot interface.", "en", "free", "curated"),
    res("res.seaborn_intro", "An Introduction to Seaborn",
        "https://seaborn.pydata.org/tutorial/introduction.html", "Seaborn", "docs",
        [("skill.matplotlib_seaborn", 1, 2)], 2, 40, "do", ["skill.pandas"],
        "Statistical data visualization built on matplotlib.", "en", "free", "curated"),
    res("res.kaggle_pandas", "Kaggle Learn: Pandas", "https://www.kaggle.com/learn/pandas",
        "Kaggle", "course", [("skill.pandas", 1, 2), ("skill.data_cleaning", 0, 1)], 2, 240, "do",
        ["skill.numpy"], "Hands-on pandas exercises: indexing, grouping, cleaning.", "en", "free", "curated"),
    res("res.kaggle_data_cleaning", "Kaggle Learn: Data Cleaning",
        "https://www.kaggle.com/learn/data-cleaning", "Kaggle", "course",
        [("skill.data_cleaning", 0, 2)], 2, 180, "do", ["skill.pandas"],
        "Missing values, scaling, parsing dates and inconsistent entries.", "en", "free", "curated"),
    res("res.kaggle_dataviz", "Kaggle Learn: Data Visualization", "https://www.kaggle.com/learn/data-visualization",
        "Kaggle", "course", [("skill.data_visualization_fundamentals", 0, 2)], 2, 240, "do",
        ["skill.pandas"], "Choosing and building the right chart for a dataset.", "en", "free", "curated"),
    res("res.kaggle_eda", "Kaggle Learn: Intro to Machine Learning",
        "https://www.kaggle.com/learn/intro-to-machine-learning", "Kaggle", "course",
        [("skill.exploratory_data_analysis", 1, 2), ("skill.ml_fundamentals", 0, 1)], 2, 180, "do",
        ["skill.pandas"], "EDA and building your first predictive model.", "en", "free", "curated"),

    # -- Excel / BI --
    res("res.msft_excel_basics", "Excel Video Training",
        "https://support.microsoft.com/en-us/office/excel-video-training-9bc05390-e94c-46af-a5b3-d7c22f6990bb",
        "Microsoft", "course", [("skill.excel", 0, 2)], 1, 240, "do", [],
        "Official Excel training: formulas, tables, pivot tables.", "en", "free", "curated"),
    res("res.exceljet_vlookup", "How to use the VLOOKUP function",
        "https://exceljet.net/excel-functions/excel-vlookup-function", "Exceljet", "article",
        [("skill.spreadsheet_formulas", 1, 2)], 2, 20, "read", ["skill.excel"],
        "Lookup formulas for combining data across spreadsheet tables.", "en", "free", "community"),
    res("res.tableau_get_started", "Tableau: Get Started",
        "https://help.tableau.com/current/guides/get-started-tutorial/en-us/get-started-tutorial-home.htm",
        "Tableau", "docs", [("skill.tableau", 0, 2)], 2, 180, "do", ["skill.data_visualization_fundamentals"],
        "Build your first interactive Tableau dashboard.", "en", "freemium", "curated"),
    res("res.powerbi_get_started", "Get started with Power BI",
        "https://learn.microsoft.com/en-us/power-bi/fundamentals/power-bi-overview",
        "Microsoft", "docs", [("skill.powerbi", 0, 2)], 2, 150, "do", ["skill.data_visualization_fundamentals"],
        "Power BI fundamentals: reports, datasets, dashboards.", "en", "free", "curated"),
    res("res.tableau_dashboards", "Best Practices for Building Dashboards",
        "https://help.tableau.com/current/blueprint/en-us/bp_dashboards.htm", "Tableau", "docs",
        [("skill.dashboarding", 1, 2)], 2, 45, "read", ["skill.tableau"],
        "Design principles for effective monitoring dashboards.", "en", "freemium", "curated"),
    res("res.hbr_data_storytelling", "How to Tell a Story with Data",
        "https://hbr.org/2013/04/how-to-tell-a-story-with-data", "Harvard Business Review", "article",
        [("skill.data_storytelling", 1, 2), ("skill.communication_stakeholders", 1, 2)], 2, 20, "read",
        ["skill.dashboarding"], "Framing analytical findings as a narrative for stakeholders.", "en", "freemium",
        "community"),

    # -- SQL / databases --
    res("res.sqlbolt", "SQLBolt: Learn SQL", "https://sqlbolt.com/",
        "SQLBolt", "course", [("skill.sql_fundamentals", 0, 2)], 1, 180, "do", [],
        "Interactive lessons on SELECT queries and filtering.", "en", "free", "curated"),
    res("res.mode_sql_joins", "SQL JOINs", "https://www.thoughtspot.com/sql-tutorial/sql-joins",
        "ThoughtSpot (formerly Mode Analytics)", "article", [("skill.sql_joins", 0, 2)], 2, 40, "read",
        ["skill.sql_fundamentals"], "INNER/LEFT/RIGHT/FULL joins explained with diagrams.", "en", "free",
        "curated"),
    res("res.mode_sql_agg", "SQL Aggregate Functions", "https://www.thoughtspot.com/sql-tutorial/sql-aggregate-functions",
        "ThoughtSpot (formerly Mode Analytics)", "article", [("skill.sql_aggregation", 0, 2)], 2, 30, "read",
        ["skill.sql_joins"], "GROUP BY, HAVING and aggregate functions.", "en", "free", "curated"),
    res("res.pg_tutorial", "PostgreSQL Tutorial", "https://www.postgresql.org/docs/current/tutorial.html",
        "PostgreSQL", "docs", [("skill.postgresql", 0, 2), ("skill.relational_modeling", 0, 1)], 2, 180, "do",
        ["skill.sql_fundamentals"], "Official PostgreSQL introduction: schemas, queries, joins.", "en", "free",
        "curated"),
    res("res.pg_indexes", "PostgreSQL: Indexes", "https://www.postgresql.org/docs/current/indexes.html",
        "PostgreSQL", "docs", [("skill.indexing_query_optimization", 1, 2)], 3, 60, "read",
        ["skill.relational_modeling"], "How indexes speed up (or fail to speed up) queries.", "en", "free",
        "curated"),
    res("res.pg_transactions", "PostgreSQL: Transactions", "https://www.postgresql.org/docs/current/tutorial-transactions.html",
        "PostgreSQL", "docs", [("skill.transactions_acid", 1, 2)], 2, 30, "read", ["skill.relational_modeling"],
        "ACID guarantees and transaction control in Postgres.", "en", "free", "curated"),
    res("res.mongodb_nosql", "NoSQL Explained", "https://www.mongodb.com/nosql-explained",
        "MongoDB", "article", [("skill.nosql_fundamentals", 0, 2)], 2, 30, "read", ["skill.sql_fundamentals"],
        "Document, key-value, wide-column and graph database models.", "en", "free", "community"),
    res("res.sqlalchemy_orm", "SQLAlchemy ORM Tutorial",
        "https://docs.sqlalchemy.org/en/20/orm/quickstart.html", "SQLAlchemy", "docs",
        [("skill.orm_usage", 0, 2)], 2, 60, "do", ["skill.postgresql", "skill.python"],
        "Mapping Python classes to relational tables with SQLAlchemy.", "en", "free", "curated"),
    res("res.alembic_tutorial", "Alembic Tutorial", "https://alembic.sqlalchemy.org/en/latest/tutorial.html",
        "SQLAlchemy", "docs", [("skill.database_migrations", 0, 2)], 2, 45, "do", ["skill.orm_usage"],
        "Writing and running schema migrations with Alembic.", "en", "free", "curated"),
    res("res.dbdesigner_normalization", "Database Normalization Explained",
        "https://www.databasestar.com/database-normalization/", "Database Star", "article",
        [("skill.relational_modeling", 1, 2)], 2, 25, "read", ["skill.sql_fundamentals"],
        "1NF-3NF normal forms with worked examples.", "en", "free", "community"),

    # -- ML fundamentals / scikit-learn --
    res("res.google_mlcc", "Machine Learning Crash Course",
        "https://developers.google.com/machine-learning/crash-course", "Google", "course",
        [("skill.ml_fundamentals", 0, 2), ("skill.supervised_learning", 0, 2)], 2, 900, "do",
        ["skill.python", "skill.descriptive_statistics"],
        "Google's guided intro to ML concepts with TensorFlow exercises.", "en", "free", "curated"),
    res("res.sklearn_getting_started", "scikit-learn: Getting Started",
        "https://scikit-learn.org/stable/getting_started.html", "scikit-learn", "docs",
        [("skill.scikit_learn", 0, 2)], 2, 45, "do", ["skill.python", "skill.numpy"],
        "Fit, predict and evaluate a model with scikit-learn's API.", "en", "free", "curated"),
    res("res.sklearn_model_eval", "scikit-learn: Model Evaluation",
        "https://scikit-learn.org/stable/modules/model_evaluation.html", "scikit-learn", "docs",
        [("skill.model_evaluation", 1, 2)], 2, 60, "read", ["skill.supervised_learning"],
        "Precision, recall, F1, ROC-AUC and other scoring metrics.", "en", "free", "curated"),
    res("res.sklearn_cv", "scikit-learn: Cross-Validation",
        "https://scikit-learn.org/stable/modules/cross_validation.html", "scikit-learn", "docs",
        [("skill.cross_validation", 0, 2)], 2, 40, "read", ["skill.overfitting_regularization"],
        "k-fold and other cross-validation strategies.", "en", "free", "curated"),
    res("res.sklearn_overfitting", "Underfitting vs. Overfitting",
        "https://scikit-learn.org/stable/auto_examples/model_selection/plot_underfitting_overfitting.html",
        "scikit-learn", "article", [("skill.overfitting_regularization", 0, 2)], 2, 20, "read",
        ["skill.supervised_learning"], "Visual example of the bias-variance tradeoff.", "en", "free", "curated"),
    res("res.sklearn_trees", "scikit-learn: Decision Trees",
        "https://scikit-learn.org/stable/modules/tree.html", "scikit-learn", "docs",
        [("skill.decision_trees_ensembles", 0, 2)], 2, 40, "read", ["skill.supervised_learning"],
        "Decision tree models and their strengths/weaknesses.", "en", "free", "curated"),
    res("res.sklearn_ensembles", "scikit-learn: Ensemble Methods",
        "https://scikit-learn.org/stable/modules/ensemble.html", "scikit-learn", "docs",
        [("skill.decision_trees_ensembles", 1, 2)], 2, 60, "read", ["skill.decision_trees_ensembles"],
        "Random forests and gradient boosting.", "en", "free", "curated"),
    res("res.sklearn_grid_search", "scikit-learn: Tuning Hyperparameters",
        "https://scikit-learn.org/stable/modules/grid_search.html", "scikit-learn", "docs",
        [("skill.hyperparameter_tuning", 0, 2)], 2, 40, "read", ["skill.scikit_learn"],
        "Grid search and randomized search over hyperparameters.", "en", "free", "curated"),
    res("res.mlcc_clustering", "Clustering in Machine Learning",
        "https://developers.google.com/machine-learning/clustering", "Google", "course",
        [("skill.clustering", 0, 2), ("skill.unsupervised_learning", 0, 2)], 2, 180, "do",
        ["skill.ml_fundamentals"], "K-means and other clustering algorithms.", "en", "free", "curated"),
    res("res.sklearn_pca", "scikit-learn: PCA", "https://scikit-learn.org/stable/modules/decomposition.html",
        "scikit-learn", "docs", [("skill.dimensionality_reduction", 0, 2)], 2, 40, "read",
        ["skill.linear_algebra_matrices"], "Principal component analysis for dimensionality reduction.",
        "en", "free", "curated"),
    res("res.shap_docs", "SHAP: Explainable AI", "https://shap.readthedocs.io/en/latest/",
        "SHAP", "docs", [("skill.model_interpretability", 1, 2)], 3, 60, "read", ["skill.model_evaluation"],
        "Explaining model predictions with Shapley values.", "en", "free", "community"),
    res("res.mlcc_feature_eng", "Feature Engineering", "https://developers.google.com/machine-learning/crash-course/representation/feature-engineering",
        "Google", "article", [("skill.feature_engineering", 0, 2)], 2, 25, "read", ["skill.supervised_learning"],
        "Turning raw data into useful model features.", "en", "free", "curated"),

    # -- deep learning / PyTorch (demo chain) --
    res("res.mlcc_nn_intro", "Introduction to Neural Networks",
        "https://developers.google.com/machine-learning/crash-course/neural-networks/nodes-hidden-layers",
        "Google", "article", [("skill.neural_network_fundamentals", 0, 2)], 2, 30, "read",
        ["skill.optimization_basics"], "Layers, weights and forward computation in a neural net.", "en", "free",
        "curated"),
    res("res.mlcc_activation", "Activation Functions",
        "https://developers.google.com/machine-learning/crash-course/neural-networks/activation-functions",
        "Google", "article", [("skill.activation_functions", 0, 2)], 2, 15, "read",
        ["skill.neural_network_fundamentals"], "Why neural nets need nonlinear activation functions.", "en",
        "free", "curated"),
    res("res.3b1b_neural_nets", "Neural Networks (playlist)", "https://www.3blue1brown.com/topics/neural-networks",
        "3Blue1Brown", "video", [("skill.neural_network_fundamentals", 1, 2), ("skill.backpropagation", 1, 2)],
        2, 150, "watch", ["skill.derivatives", "skill.linear_algebra_matrices"],
        "Visual, worked-example-first walkthrough of how backpropagation computes gradients.", "en", "free",
        "curated"),
    res("res.cs231n_backprop", "CS231n: Backpropagation Notes",
        "https://cs231n.github.io/optimization-2/", "Stanford CS231n", "article",
        [("skill.backpropagation", 1, 3)], 2, 45, "read", ["skill.chain_rule", "skill.neural_network_fundamentals"],
        "How the chain rule composes local gradients through a computation graph.", "en", "free", "curated"),
    res("res.pytorch_autograd", "PyTorch: A Gentle Introduction to torch.autograd",
        "https://pytorch.org/tutorials/beginner/blitz/autograd_tutorial.html", "PyTorch", "docs",
        [("skill.backpropagation", 1, 2), ("skill.pytorch", 0, 1)], 2, 30, "do",
        ["skill.python", "skill.chain_rule"], "How PyTorch computes gradients automatically via autograd.",
        "en", "free", "curated"),
    res("res.pytorch_60min", "Deep Learning with PyTorch: A 60 Minute Blitz",
        "https://pytorch.org/tutorials/beginner/deep_learning_60min_blitz.html", "PyTorch", "docs",
        [("skill.pytorch", 0, 2), ("skill.training_neural_networks", 0, 2)], 2, 60, "do",
        ["skill.python", "skill.neural_network_fundamentals"],
        "Tensors, autograd and a full training loop in PyTorch.", "en", "free", "curated"),
    res("res.pytorch_optim", "PyTorch: Optimizing Model Parameters",
        "https://pytorch.org/tutorials/beginner/basics/optimization_tutorial.html", "PyTorch", "docs",
        [("skill.training_neural_networks", 1, 2), ("skill.gradient_descent_variants", 1, 2)], 2, 40, "do",
        ["skill.pytorch", "skill.loss_functions"], "The training loop: loss, backward pass, optimizer step.",
        "en", "free", "curated"),
    res("res.pytorch_loss", "PyTorch: Loss Functions", "https://pytorch.org/docs/stable/nn.html#loss-functions",
        "PyTorch", "docs", [("skill.loss_functions", 0, 2)], 2, 30, "read", ["skill.neural_network_fundamentals"],
        "Reference for PyTorch's built-in loss functions.", "en", "free", "curated"),
    res("res.d2l_optimization", "Dive into Deep Learning: Optimization Algorithms",
        "https://d2l.ai/chapter_optimization/index.html", "d2l.ai", "book_chapter",
        [("skill.gradient_descent_variants", 1, 3)], 3, 90, "read", ["skill.optimization_basics"],
        "SGD, momentum, Adam and other optimizers used to train deep nets.", "en", "free", "curated"),
    res("res.pytorch_batchnorm", "PyTorch: BatchNorm2d", "https://pytorch.org/docs/stable/generated/torch.nn.BatchNorm2d.html",
        "PyTorch", "docs", [("skill.batch_normalization", 1, 2)], 3, 20, "read",
        ["skill.training_neural_networks"], "Reference for applying batch normalization in PyTorch.", "en",
        "free", "curated"),
    res("res.d2l_regularization", "Dive into Deep Learning: Regularization",
        "https://d2l.ai/chapter_multilayer-perceptrons/dropout.html", "d2l.ai", "book_chapter",
        [("skill.regularization_dl", 1, 2)], 2, 40, "read", ["skill.training_neural_networks"],
        "Dropout and weight decay for regularizing deep nets.", "en", "free", "curated"),
    res("res.tf_keras_overview", "TensorFlow: Keras Overview", "https://www.tensorflow.org/guide/keras",
        "TensorFlow", "docs", [("skill.tensorflow_keras", 0, 2)], 2, 45, "do", ["skill.python"],
        "Building and training models with the Keras API.", "en", "free", "curated"),
    res("res.cs231n_cnn", "CS231n: Convolutional Neural Networks",
        "https://cs231n.github.io/convolutional-networks/", "Stanford CS231n", "article",
        [("skill.cnn", 0, 2)], 2, 60, "read", ["skill.training_neural_networks"],
        "How convolution, pooling and CNN layers work.", "en", "free", "curated"),
    res("res.pytorch_cifar", "PyTorch: Training a Classifier", "https://pytorch.org/tutorials/beginner/blitz/cifar10_tutorial.html",
        "PyTorch", "docs", [("skill.cnn_image_classification", 0, 2)], 2, 45, "do",
        ["skill.pytorch", "skill.cnn"], "Train a CNN image classifier end-to-end in PyTorch.", "en", "free",
        "curated"),
    res("res.colah_lstm", "Understanding LSTM Networks", "https://colah.github.io/posts/2015-08-Understanding-LSTMs/",
        "Christopher Olah", "article", [("skill.rnn_sequence_models", 1, 2)], 3, 30, "read",
        ["skill.training_neural_networks"], "Visual explanation of LSTM/GRU sequence models.", "en", "free",
        "curated"),
    res("res.illustrated_transformer", "The Illustrated Transformer",
        "https://jalammar.github.io/illustrated-transformer/", "Jay Alammar", "article",
        [("skill.transformers_attention", 0, 2)], 3, 40, "read", ["skill.rnn_sequence_models"],
        "Step-by-step visual walkthrough of the transformer architecture.", "en", "free", "curated"),
    res("res.pytorch_transfer", "PyTorch: Transfer Learning Tutorial",
        "https://pytorch.org/tutorials/beginner/transfer_learning_tutorial.html", "PyTorch", "docs",
        [("skill.transfer_learning", 0, 2)], 2, 45, "do", ["skill.cnn"],
        "Fine-tuning a pretrained CNN on a new dataset.", "en", "free", "curated"),

    # -- computer vision --
    res("res.opencv_getting_started", "OpenCV-Python Tutorials",
        "https://docs.opencv.org/4.x/d6/d00/tutorial_py_root.html", "OpenCV", "docs",
        [("skill.opencv", 0, 2), ("skill.image_processing_basics", 0, 1)], 1, 180, "do", ["skill.python"],
        "Official OpenCV-Python tutorial series.", "en", "free", "curated"),
    res("res.ultralytics_yolo_docs", "Ultralytics YOLO Docs", "https://docs.ultralytics.com/",
        "Ultralytics", "docs", [("skill.object_detection", 0, 2)], 2, 90, "do",
        ["skill.cnn_image_classification"], "Training and running YOLO object-detection models.", "en", "free",
        "curated"),
    res("res.ultralytics_segmentation", "Instance Segmentation with Ultralytics YOLO",
        "https://docs.ultralytics.com/tasks/segment/", "Ultralytics", "docs",
        [("skill.image_segmentation", 1, 2)], 3, 45, "do", ["skill.object_detection"],
        "Training and running instance segmentation models.", "en", "free", "curated"),

    # -- NLP / LLMs --
    res("res.hf_nlp_course", "Hugging Face NLP Course", "https://huggingface.co/learn/nlp-course",
        "Hugging Face", "course", [("skill.nlp_fundamentals", 0, 2), ("skill.huggingface", 0, 2)], 2, 600,
        "do", ["skill.python"], "Tokenization, transformers and the Hugging Face ecosystem.", "en", "free",
        "curated"),
    res("res.word2vec_paper_explained", "Word2Vec Explained",
        "https://jalammar.github.io/illustrated-word2vec/", "Jay Alammar", "article",
        [("skill.word_embeddings", 0, 2)], 2, 30, "read", ["skill.nlp_fundamentals"],
        "Visual explanation of word embeddings and word2vec.", "en", "free", "curated"),
    res("res.hf_llm_course", "Hugging Face LLM Course", "https://huggingface.co/learn/llm-course",
        "Hugging Face", "course", [("skill.llm_basics", 0, 2)], 2, 480, "do", ["skill.transformers_attention"],
        "How large language models are built, trained and used.", "en", "free", "curated"),
    res("res.openai_prompt_guide", "Prompt Engineering Guide",
        "https://platform.openai.com/docs/guides/prompt-engineering", "OpenAI", "docs",
        [("skill.prompt_engineering", 0, 2)], 2, 45, "read", ["skill.llm_basics"],
        "Techniques for writing effective prompts.", "en", "free", "curated"),

    # -- MLOps --
    res("res.mlflow_quickstart", "MLflow Quickstart", "https://mlflow.org/docs/latest/getting-started/",
        "MLflow", "docs", [("skill.experiment_tracking", 0, 2)], 2, 40, "do", ["skill.python"],
        "Logging parameters, metrics and models with MLflow.", "en", "free", "curated"),
    res("res.wandb_quickstart", "Weights & Biases Quickstart", "https://docs.wandb.ai/quickstart/",
        "Weights & Biases", "docs", [("skill.experiment_tracking", 1, 2), ("skill.model_versioning", 0, 1)],
        2, 30, "do", ["skill.python"], "Tracking experiments and model versions with W&B.", "en", "freemium",
        "curated"),
    res("res.fastapi_first_steps", "FastAPI: First Steps", "https://fastapi.tiangolo.com/tutorial/first-steps/",
        "FastAPI", "docs", [("skill.model_serving", 0, 2), ("skill.backend_framework", 0, 1)], 1, 30, "do",
        ["skill.python"], "Serve a model behind a REST endpoint with FastAPI.", "en", "free", "curated"),
    res("res.evidently_drift", "Evidently AI: Data Drift", "https://docs.evidentlyai.com/introduction",
        "Evidently AI", "docs", [("skill.ml_monitoring", 0, 2)], 2, 40, "read", ["skill.model_serving"],
        "Detecting data/model drift once a model is in production.", "en", "free", "community"),
    res("res.mlcc_production_ml", "Production ML Systems", "https://developers.google.com/machine-learning/crash-course/production-ml-systems",
        "Google", "course", [("skill.mlops_fundamentals", 0, 2), ("skill.data_pipelines", 0, 2)], 2, 90, "read",
        ["skill.ml_fundamentals"], "Operating ML systems reliably end-to-end.", "en", "free", "curated"),

    # -- backend engineering --
    res("res.mdn_http_overview", "An Overview of HTTP", "https://developer.mozilla.org/en-US/docs/Web/HTTP/Overview",
        "MDN Web Docs", "docs", [("skill.http_fundamentals", 0, 2)], 1, 30, "read", [],
        "Request/response cycle, methods and status codes.", "en", "free", "curated"),
    res("res.restfulapi_design", "REST API Design Best Practices",
        "https://restfulapi.net/", "RESTfulAPI.net", "article", [("skill.rest_api_design", 0, 2)], 2, 60,
        "read", ["skill.http_fundamentals"], "Resource modeling and conventions for REST APIs.", "en", "free",
        "community"),
    res("res.fastapi_tutorial", "FastAPI Tutorial", "https://fastapi.tiangolo.com/tutorial/",
        "FastAPI", "docs", [("skill.backend_framework", 0, 2)], 2, 240, "do", ["skill.rest_api_design"],
        "Building a full REST API with FastAPI.", "en", "free", "curated"),
    res("res.expressjs_guide", "Express.js Guide", "https://expressjs.com/en/guide/routing.html",
        "Express.js", "docs", [("skill.backend_framework", 1, 2)], 2, 60, "do", ["skill.rest_api_design"],
        "Routing and middleware in Express.js.", "en", "free", "curated"),
    res("res.jwt_intro", "JWT Introduction", "https://jwt.io/introduction",
        "jwt.io", "article", [("skill.authentication_authorization", 0, 2)], 2, 25, "read",
        ["skill.rest_api_design"], "How JSON Web Tokens encode and (only) sign claims.", "en", "free", "curated"),
    res("res.owasp_top10", "OWASP Top 10", "https://owasp.org/www-project-top-ten/",
        "OWASP", "docs", [("skill.web_security_owasp", 0, 2), ("skill.security_fundamentals", 0, 2)], 2, 90,
        "read", ["skill.authentication_authorization"], "The ten most critical web application security risks.",
        "en", "free", "curated"),
    res("res.redis_caching", "Redis: Caching", "https://redis.io/docs/latest/develop/use/patterns/",
        "Redis", "docs", [("skill.caching", 0, 2)], 2, 40, "read", ["skill.backend_framework"],
        "Common caching patterns with Redis.", "en", "free", "curated"),
    res("res.rabbitmq_tutorial", "RabbitMQ Tutorial: Hello World",
        "https://www.rabbitmq.com/tutorials/tutorial-one-python.html", "RabbitMQ", "docs",
        [("skill.message_queues", 0, 2)], 2, 40, "do", ["skill.backend_framework"],
        "Sending and receiving messages with a message queue.", "en", "free", "curated"),
    res("res.martinfowler_microservices", "Microservices", "https://martinfowler.com/articles/microservices.html",
        "Martin Fowler", "article", [("skill.microservices", 0, 2)], 3, 40, "read", ["skill.rest_api_design"],
        "What microservices are and the tradeoffs of adopting them.", "en", "free", "curated"),
    res("res.systemdesign_primer", "System Design Primer", "https://github.com/donnemartin/system-design-primer",
        "GitHub (donnemartin)", "docs", [("skill.system_design_fundamentals", 0, 2)], 3, 300, "read",
        ["skill.microservices"], "A broad tour of scalable system design concepts.", "en", "free", "curated"),
    res("res.nginx_load_balancing", "Load Balancing with NGINX",
        "https://docs.nginx.com/nginx/admin-guide/load-balancer/http-load-balancer/", "NGINX", "docs",
        [("skill.load_balancing", 0, 2)], 2, 30, "read", ["skill.system_design_fundamentals"],
        "Distributing HTTP traffic across backend servers.", "en", "free", "curated"),
    res("res.postman_learning", "Postman Learning Center: API Testing",
        "https://learning.postman.com/docs/getting-started/introduction/", "Postman", "docs",
        [("skill.api_testing", 0, 2)], 1, 45, "do", ["skill.rest_api_design"],
        "Testing REST APIs with Postman collections.", "en", "free", "curated"),
    res("res.mdn_websockets", "Writing WebSocket Client Applications",
        "https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API/Writing_WebSocket_client_applications",
        "MDN Web Docs", "docs", [("skill.websockets", 0, 2)], 2, 30, "read", ["skill.rest_api_design"],
        "Bidirectional real-time communication with WebSockets.", "en", "free", "curated"),
    res("res.swagger_openapi", "OpenAPI Specification", "https://swagger.io/docs/specification/about/",
        "Swagger", "docs", [("skill.api_documentation", 0, 2)], 2, 40, "read", ["skill.rest_api_design"],
        "Documenting a REST API with the OpenAPI spec.", "en", "free", "curated"),
    res("res.graphql_learn", "Introduction to GraphQL", "https://graphql.org/learn/",
        "GraphQL.org", "docs", [("skill.graphql", 0, 2)], 2, 60, "read", ["skill.rest_api_design"],
        "Schemas, queries and resolvers in GraphQL.", "en", "free", "curated"),
    res("res.grpc_intro", "gRPC: Introduction", "https://grpc.io/docs/what-is-grpc/introduction/",
        "gRPC", "docs", [("skill.rest_vs_grpc", 0, 2)], 2, 30, "read", ["skill.rest_api_design"],
        "When and how to use gRPC instead of REST.", "en", "free", "curated"),
    res("res.stripe_idempotency", "Idempotent Requests", "https://stripe.com/docs/api/idempotent_requests",
        "Stripe", "docs", [("skill.idempotency", 0, 2)], 2, 20, "read", ["skill.rest_api_design"],
        "Designing retry-safe API requests.", "en", "free", "curated"),
    res("res.cloudflare_rate_limiting", "What Is Rate Limiting?",
        "https://www.cloudflare.com/learning/bots/what-is-rate-limiting/", "Cloudflare", "article",
        [("skill.rate_limiting", 0, 2)], 1, 15, "read", ["skill.backend_framework"],
        "Why and how to rate-limit an API.", "en", "free", "curated"),
    res("res.12factor_config", "The Twelve-Factor App: Config", "https://12factor.net/config",
        "12factor.net", "article", [("skill.env_config_management", 0, 2)], 1, 15, "read",
        ["skill.backend_framework"], "Storing config in the environment, not in code.", "en", "free", "curated"),

    # -- devops / infrastructure --
    res("res.docker_get_started", "Docker: Get Started", "https://docs.docker.com/get-started/",
        "Docker", "docs", [("skill.docker", 0, 2)], 1, 90, "do", ["skill.linux_fundamentals"],
        "Building and running your first containers.", "en", "free", "curated"),
    res("res.k8s_basics", "Kubernetes Basics", "https://kubernetes.io/docs/tutorials/kubernetes-basics/",
        "Kubernetes", "docs", [("skill.kubernetes_basics", 0, 2)], 3, 240, "do", ["skill.docker"],
        "Deploying and scaling containerized apps with Kubernetes.", "en", "free", "curated"),
    res("res.github_actions_quickstart", "GitHub Actions Quickstart",
        "https://docs.github.com/en/actions/quickstart", "GitHub", "docs", [("skill.ci_cd", 0, 2)], 2, 45,
        "do", ["skill.git", "skill.testing_fundamentals"], "Automating build/test/deploy with GitHub Actions.",
        "en", "free", "curated"),
    res("res.aws_cloud_practitioner", "AWS Cloud Practitioner Essentials",
        "https://aws.amazon.com/training/digital/aws-cloud-practitioner-essentials/", "AWS", "course",
        [("skill.cloud_fundamentals", 0, 2)], 2, 360, "do", [], "Core AWS services and cloud concepts.", "en",
        "free", "curated"),
    res("res.aws_pricing_calc", "AWS Pricing Calculator", "https://calculator.aws/",
        "AWS", "docs", [("skill.cost_estimation_cloud", 0, 1)], 1, 20, "do", ["skill.cloud_fundamentals"],
        "Estimating the cost of a planned cloud architecture.", "en", "free", "curated"),
    res("res.terraform_get_started", "Terraform: Get Started",
        "https://developer.hashicorp.com/terraform/tutorials/aws-get-started", "HashiCorp", "docs",
        [("skill.infrastructure_as_code", 0, 2)], 3, 90, "do", ["skill.cloud_fundamentals"],
        "Defining infrastructure declaratively with Terraform.", "en", "free", "curated"),
    res("res.grafana_intro", "Introduction to Grafana", "https://grafana.com/docs/grafana/latest/introduction/",
        "Grafana Labs", "docs", [("skill.logging_monitoring", 0, 2)], 2, 40, "read", ["skill.backend_framework"],
        "Dashboards and alerting for observability.", "en", "free", "curated"),

    # -- git / collaboration --
    res("res.git_pro_book", "Pro Git Book (Getting Started)", "https://git-scm.com/book/en/v2",
        "git-scm.com", "book_chapter", [("skill.git", 0, 2)], 1, 180, "do", ["skill.cli_basics"],
        "The official, free book covering Git from first commit to branching.", "en", "free", "curated"),
    res("res.github_flow", "GitHub Flow", "https://docs.github.com/en/get-started/using-github/github-flow",
        "GitHub", "docs", [("skill.github_workflow", 0, 2), ("skill.version_control_branching", 0, 2)], 1, 20,
        "read", ["skill.git"], "A lightweight branch-based workflow for collaborating on GitHub.", "en", "free",
        "curated"),
    res("res.google_code_review", "Google Engineering Practices: Code Review",
        "https://google.github.io/eng-practices/review/", "Google", "docs",
        [("skill.code_review_practice", 0, 2)], 2, 60, "read", ["skill.github_workflow"],
        "Standards and etiquette for giving/receiving code review.", "en", "free", "curated"),
    res("res.atlassian_agile", "Agile Project Management with Scrum",
        "https://www.atlassian.com/agile/scrum", "Atlassian", "article", [("skill.agile_practices", 0, 1)],
        1, 30, "read", [], "Sprints, standups and backlogs in Scrum.", "en", "free", "curated"),
    res("res.writethedocs_guide", "Write the Docs: Documentation Guide",
        "https://www.writethedocs.org/guide/", "Write the Docs", "docs",
        [("skill.documentation_practice", 0, 2)], 2, 60, "read", [], "Principles for writing clear technical docs.",
        "en", "free", "community"),

    # -- data analysis (business) --
    res("res.mode_business_analysis", "SQL Tutorial for Data Analysis (Business Analytics with SQL)",
        "https://www.thoughtspot.com/sql-tutorial/introduction-to-sql", "ThoughtSpot (formerly Mode Analytics)",
        "course", [("skill.business_requirements_analysis", 1, 2)], 2, 120, "do", ["skill.sql_fundamentals"],
        "Turning business questions into SQL analysis.", "en", "free", "community"),
    res("res.kimball_kpi", "How to Choose the Right KPIs",
        "https://www.klipfolio.com/resources/articles/what-is-a-key-performance-indicator", "Klipfolio",
        "article", [("skill.kpi_metrics_design", 0, 2)], 2, 20, "read", ["skill.business_requirements_analysis"],
        "Defining metrics that track a real business outcome.", "en", "free", "community"),
    res("res.dama_data_governance", "What Is Data Governance?",
        "https://www.dataversity.net/what-is-data-governance/", "DATAVERSITY", "article",
        [("skill.data_governance", 0, 1)], 1, 20, "read", [], "Policies that keep organizational data trustworthy.",
        "en", "free", "community"),
    res("res.ftc_privacy", "Data Privacy Basics", "https://www.ftc.gov/business-guidance/privacy-security",
        "FTC", "article", [("skill.data_ethics_privacy", 0, 1)], 1, 20, "read", ["skill.data_governance"],
        "Regulatory and ethical basics of handling personal data.", "en", "free", "curated"),
    res("res.etl_fundamentals_article", "ETL vs ELT: What's the Difference?",
        "https://www.stitchdata.com/resources/etl-vs-elt/", "Stitch", "article",
        [("skill.etl_fundamentals", 0, 1)], 1, 15, "read", ["skill.sql_fundamentals"],
        "Extract-transform-load pipelines and how they move data.", "en", "free", "community"),
    res("res.mode_time_series", "SQL Window Functions (for time series analysis)",
        "https://www.thoughtspot.com/sql-tutorial/sql-window-functions", "ThoughtSpot (formerly Mode Analytics)",
        "article", [("skill.time_series_analysis", 1, 2)], 2, 30, "read",
        ["skill.descriptive_statistics"], "Window functions and trend analysis over time-ordered data.", "en",
        "free", "community"),

    # -- security --
    res("res.owasp_cheatsheets", "OWASP Cheat Sheet Series", "https://cheatsheetseries.owasp.org/",
        "OWASP", "docs", [("skill.security_fundamentals", 1, 2)], 2, 90, "read", [],
        "Practical, per-topic secure-coding cheat sheets.", "en", "free", "curated"),

    # -- fill remaining role-required skills with 0 coverage --
    res("res.py_control_flow", "More Control Flow Tools", "https://docs.python.org/3/tutorial/controlflow.html",
        "Python Software Foundation", "docs", [("skill.control_flow", 0, 1),
        ("skill.programming_fundamentals", 0, 1)], 1, 40, "read", [],
        "if/for/while and other control-flow constructs in Python.", "en", "free", "curated"),
    res("res.py_functions", "Defining Functions", "https://docs.python.org/3/tutorial/controlflow.html#defining-functions",
        "Python Software Foundation", "docs", [("skill.functions_modularity", 0, 1)], 1, 30, "read",
        ["skill.control_flow"], "Defining and calling functions, default/keyword arguments.", "en", "free",
        "curated"),
    res("res.rp_debugging", "Python Debugging With Pdb", "https://realpython.com/python-debugging-pdb/",
        "Real Python", "article", [("skill.debugging", 0, 2)], 2, 35, "do", ["skill.programming_fundamentals"],
        "Systematically isolating bugs using Python's interactive debugger.", "en", "free", "curated"),
    res("res.fcc_command_line", "Command Line for Beginners",
        "https://www.freecodecamp.org/news/command-line-for-beginners/", "freeCodeCamp", "article",
        [("skill.cli_basics", 0, 1)], 1, 45, "read", [],
        "Navigating files and running programs from a Unix shell.", "en", "free", "curated"),
    res("res.ubuntu_cli_tutorial", "The Linux Command Line for Beginners",
        "https://ubuntu.com/tutorials/command-line-for-beginners", "Canonical / Ubuntu", "course",
        [("skill.linux_fundamentals", 0, 2)], 1, 90, "do", ["skill.cli_basics"],
        "Processes, permissions and the Linux filesystem, hands-on.", "en", "free", "curated"),
]

RESOURCE_IDS = {r["resource_id"] for r in RESOURCES}


# --------------------------------------------------------------------------
# 5. MISCONCEPTION CATALOG (for demo-critical + a representative spread of
#    other core skills). remediation_candidates reference resource_ids above.
# --------------------------------------------------------------------------

MISCONCEPTIONS = [
    misc("misc.chain_rule_sum",
         "Differentiates a composite function as a sum of the parts' derivatives "
         "instead of their product.",
         "skill.backpropagation", "skill.chain_rule",
         "Given f(g(x)), computes f'(x) + g'(x) instead of f'(g(x)) * g'(x); in a network, "
         "this shows up as adding rather than multiplying layer-local gradients.",
         ["res.khan_diff_calc", "res.3b1b_calculus", "res.cs231n_backprop"], "high"),
    misc("misc.backprop_local_gradient_only",
         "Believes each layer's weight update uses only that layer's local error, ignoring "
         "gradients flowing back from downstream layers.",
         "skill.backpropagation", "skill.neural_network_fundamentals",
         "Updates a hidden layer as if it were the output layer, skipping the upstream chain "
         "of partial derivatives entirely.",
         ["res.cs231n_backprop", "res.3b1b_neural_nets"], "medium"),
    misc("misc.vanishing_gradient_confusion",
         "Believes a plateauing training loss always means the model has converged optimally, "
         "rather than considering vanishing/exploding gradients.",
         "skill.training_neural_networks", "skill.backpropagation",
         "Stops debugging a stalled training run because 'the loss curve is flat', without "
         "checking gradient magnitudes or learning rate.",
         ["res.d2l_optimization", "res.pytorch_optim"], "medium"),
    misc("misc.overfitting_is_just_memorizing",
         "Believes overfitting can only happen with very small datasets and cannot happen once "
         "there is 'enough' data.",
         "skill.overfitting_regularization", "skill.supervised_learning",
         "Dismisses a large train/validation gap as impossible given dataset size, rather than "
         "checking model capacity vs. data complexity.",
         ["res.sklearn_overfitting", "res.sklearn_cv"], "medium"),
    misc("misc.cv_prevents_overfitting",
         "Believes running cross-validation itself prevents overfitting, rather than merely "
         "detecting/estimating it.",
         "skill.cross_validation", "skill.overfitting_regularization",
         "Adds k-fold CV to a pipeline and assumes the resulting model is now regularized, with "
         "no other changes made.",
         ["res.sklearn_cv"], "low"),
    misc("misc.relu_always_better",
         "Believes ReLU has no drawbacks and should replace sigmoid/softmax everywhere, "
         "including output layers for probabilities.",
         "skill.activation_functions", "skill.neural_network_fundamentals",
         "Uses ReLU on a final classification layer where a bounded probability output "
         "(softmax/sigmoid) is required.",
         ["res.mlcc_activation"], "low"),
    misc("misc.sgd_same_as_gd",
         "Believes stochastic gradient descent and full-batch gradient descent always follow "
         "the same trajectory, ignoring sampling noise.",
         "skill.gradient_descent_variants", "skill.optimization_basics",
         "Expects a single-example SGD step to reduce loss on the whole training set every "
         "step, the way a full-batch step would.",
         ["res.d2l_optimization", "res.mlcc_gradient_descent"], "low"),
    misc("misc.sql_inner_join_default_keeps_all",
         "Believes INNER JOIN keeps all rows from both tables, similar to a UNION.",
         "skill.sql_joins", "skill.sql_fundamentals",
         "Expects unmatched rows from either table to appear (with NULLs) in an INNER JOIN "
         "result, then is surprised rows are missing.",
         ["res.mode_sql_joins"], "medium"),
    misc("misc.left_join_symmetric",
         "Believes LEFT JOIN and RIGHT JOIN with the tables in the same order return the same "
         "rows, missing that row-preservation direction matters.",
         "skill.sql_joins", "skill.sql_fundamentals",
         "Swaps LEFT JOIN for RIGHT JOIN (same table order) expecting identical output.",
         ["res.mode_sql_joins"], "low"),
    misc("misc.pvalue_probability_null_true",
         "Believes a p-value is the probability that the null hypothesis is true.",
         "skill.hypothesis_testing", "skill.probability_distributions",
         "States 'p = 0.03 means there's a 3% chance the null hypothesis is true', a direct "
         "misreading of what a p-value conditions on.",
         ["res.khan_inference"], "high"),
    misc("misc.confidence_interval_contains_true_value_95pct",
         "Believes a 95% confidence interval means there's a 95% chance the true parameter lies "
         "in this specific computed interval.",
         "skill.hypothesis_testing", "skill.inferential_statistics",
         "Interprets one already-computed 95% CI as having a 95% chance of containing the true "
         "population parameter, rather than describing the procedure's long-run coverage.",
         ["res.khan_confidence"], "medium"),
    misc("misc.recursion_no_base_case_needed",
         "Believes a recursive function will naturally terminate as long as the input 'gets "
         "smaller', without an explicit base case.",
         "skill.recursion", "skill.functions_modularity",
         "Writes a recursive function with only a recursive call and no explicit stopping "
         "condition, causing infinite recursion / stack overflow.",
         ["res.gfg_recursion"], "medium"),
    misc("misc.big_o_worst_case_only_matters",
         "Conflates Big-O with worst-case runtime specifically, not realizing O/Θ/Ω describe "
         "upper/tight/lower bounds independent of best/average/worst case.",
         "skill.big_o", "skill.dsa_sorting_searching",
         "States an algorithm 'is O(n log n)' meaning strictly worst-case, then is confused "
         "when a source describes its average-case bound the same way.",
         ["res.cs_bigo"], "low"),
    misc("misc.rest_get_can_mutate",
         "Believes it's acceptable to perform state-mutating writes inside a GET endpoint since "
         "'it still works'.",
         "skill.rest_api_design", "skill.http_fundamentals",
         "Implements a GET /delete-item endpoint, breaking caching, prefetching and idempotency "
         "assumptions that depend on GET being safe.",
         ["res.restfulapi_design", "res.mdn_http_overview"], "medium"),
    misc("misc.jwt_is_encrypted",
         "Believes a JWT's payload is encrypted and therefore safe to store secrets in, when it "
         "is only signed and base64-encoded (readable by anyone).",
         "skill.authentication_authorization", "skill.security_fundamentals",
         "Puts a plaintext secret or password inside a JWT claim, assuming it can't be read by "
         "the client that holds the token.",
         ["res.jwt_intro", "res.owasp_top10"], "high"),
    misc("misc.unit_tests_prove_no_bugs",
         "Believes a fully passing unit test suite proves the absence of bugs, rather than only "
         "the absence of the specific behaviors tested.",
         "skill.testing_fundamentals", "skill.error_handling",
         "Ships a change on 'all tests green' without considering untested edge cases or "
         "integration behavior.",
         ["res.pytest_docs"], "low"),
    misc("misc.docker_image_is_running_container",
         "Conflates a Docker image with a running container, believing stopping a container "
         "deletes its image.",
         "skill.docker", "skill.linux_fundamentals",
         "Runs `docker stop` and then expects `docker run` on the same image to fail because "
         "'the container/image is gone'.",
         ["res.docker_get_started"], "low"),
    misc("misc.normalization_removes_all_duplication",
         "Believes fully normalizing a relational schema (3NF and beyond) always improves query "
         "performance.",
         "skill.relational_modeling", "skill.sql_fundamentals",
         "Over-normalizes a reporting table into many joins, then is surprised query latency "
         "gets worse, not better.",
         ["res.dbdesigner_normalization"], "medium"),
]

MISCONCEPTION_IDS = {m["misconception_id"] for m in MISCONCEPTIONS}


# --------------------------------------------------------------------------
# 6. ASSESSMENT ITEM BANK (initial, curated). Full ≥6-items-per-assessable-
#    skill coverage across all ~150 skills is future work (see
#    IMPLEMENTATION_STATE.md); this seeds the demo chain and a representative
#    spread of other core skills to a validated standard.
# --------------------------------------------------------------------------

ITEMS = []


def add_items(skill_id, entries):
    for idx, (difficulty, purpose, question, options, explanation) in enumerate(entries, start=1):
        short = skill_id.split(".", 1)[1]
        ITEMS.append(item(f"item.{short}.{idx}", skill_id, difficulty, question, options, explanation, purpose))


add_items("skill.derivatives", [
    ("easy", "practice", "What does the derivative of a function at a point represent?",
     [("The instantaneous rate of change of the function at that point", True, None),
      ("The average value of the function over its domain", False, None),
      ("The area under the curve up to that point", False, None),
      ("The maximum value the function can reach", False, None)],
     "The derivative is the instantaneous slope / rate of change at a point."),
    ("easy", "practice", "What is d/dx of x^3?",
     [("3x^2", True, None), ("x^2", False, None), ("3x", False, None), ("x^3/3", False, None)],
     "Power rule: d/dx x^n = n*x^(n-1), so d/dx x^3 = 3x^2."),
    ("medium", "practice", "What is d/dx of (5x)?",
     [("5", True, None), ("5x", False, None), ("x", False, None), ("0", False, None)],
     "The derivative of a linear function ax is its constant slope a."),
    ("medium", "practice", "If f(x) = x^2 + 3x, what is f'(x)?",
     [("2x + 3", True, None), ("2x + 3x", False, None), ("x + 3", False, None), ("2x", False, None)],
     "Differentiate term by term: d/dx x^2 = 2x, d/dx 3x = 3."),
])

add_items("skill.chain_rule", [
    ("easy", "practice", "The chain rule is used to differentiate what kind of function?",
     [("A composite function, i.e. a function of a function", True, None),
      ("A sum of two functions", False, None),
      ("A product of two constants", False, None),
      ("An integral", False, None)],
     "The chain rule differentiates compositions f(g(x))."),
    ("medium", "practice", "For f(x) = (3x + 1)^2, what is f'(x) using the chain rule?",
     [("2*(3x+1)*3 = 6*(3x+1)", True, "misc.chain_rule_sum"),
      ("2*(3x+1) + 3", False, "misc.chain_rule_sum"),
      ("2*(3x+1)", False, None),
      ("6x + 1", False, None)],
     "Chain rule: d/dx [g(x)]^2 = 2*g(x)*g'(x); here g(x)=3x+1 so g'(x)=3, giving 6*(3x+1)."),
    ("medium", "prereq-block", "If y = f(u) and u = g(x), what is dy/dx?",
     [("dy/du * du/dx", True, None), ("dy/du + du/dx", False, "misc.chain_rule_sum"),
      ("dy/du - du/dx", False, None), ("du/dx alone", False, None)],
     "The chain rule composes derivatives by multiplication, not addition: dy/dx = dy/du * du/dx."),
    ("medium", "prereq-block", "For h(x) = sin(x^2), what is h'(x)?",
     [("cos(x^2) * 2x", True, "misc.chain_rule_sum"),
      ("cos(x^2) + 2x", False, "misc.chain_rule_sum"),
      ("-cos(x^2) * 2x", False, None),
      ("2x * sin(x)", False, None)],
     "Outer derivative cos(x^2) times inner derivative 2x, multiplied per the chain rule."),
    ("hard", "practice", "For f(x) = e^(3x^2), what is f'(x)?",
     [("6x * e^(3x^2)", True, "misc.chain_rule_sum"),
      ("3x^2 * e^(3x^2) + 6x", False, "misc.chain_rule_sum"),
      ("e^(3x^2)", False, None),
      ("6x + e^(3x^2)", False, None)],
     "Outer derivative e^(3x^2) times inner derivative 6x, multiplied, not added."),
    ("hard", "practice", "For f(x) = ln(cos(x)), what is f'(x)?",
     [("-tan(x)", True, None), ("1/cos(x) - sin(x)", False, "misc.chain_rule_sum"),
      ("-sin(x)*cos(x)", False, None), ("tan(x)", False, None)],
     "d/dx ln(cos(x)) = (1/cos(x)) * (-sin(x)) = -tan(x), by the chain rule."),
])

add_items("skill.neural_network_fundamentals", [
    ("easy", "practice", "In a feedforward neural network, what does a single neuron compute?",
     [("A weighted sum of its inputs plus a bias, passed through an activation function", True, None),
      ("The average of all inputs in the network", False, None),
      ("A random number used for initialization", False, None),
      ("The final class label directly", False, None)],
     "A neuron computes activation(w·x + b)."),
    ("easy", "practice", "What is the role of weights in a neural network?",
     [("They scale the contribution of each input to a neuron's output", True, None),
      ("They store the final predictions", False, None),
      ("They determine the learning rate", False, None),
      ("They count the number of training epochs", False, None)],
     "Weights are learned parameters that scale each input's contribution."),
    ("medium", "practice", "Why do neural networks need a nonlinear activation function?",
     [("Without nonlinearity, stacking layers collapses to a single linear transform", True, None),
      ("Nonlinearity makes training faster in all cases", False, None),
      ("It is only needed for image data", False, None),
      ("It replaces the need for a loss function", False, None)],
     "Composing only linear layers is still linear; nonlinearity gives networks their expressive power."),
    ("medium", "practice", "What is a 'hidden layer' in a neural network?",
     [("Any layer between the input and output layers", True, None),
      ("A layer whose weights are never updated", False, None),
      ("A layer that is only used at inference time", False, None),
      ("The layer that computes the loss", False, None)],
     "Hidden layers sit between input and output and are not directly observed."),
    ("hard", "probe", "Why is weight initialization important for training deep networks?",
     [("Poor initialization can cause vanishing or exploding activations/gradients", True, None),
      ("It only affects the final accuracy, never training stability", False, None),
      ("Weights are never actually initialized; they start at zero", False, None),
      ("It only matters for convolutional layers", False, None)],
     "Initialization scale interacts with depth and activation choice to affect gradient flow."),
    ("hard", "practice", "What distinguishes a network's capacity from its generalization?",
     [("Capacity is how complex a function it can represent; generalization is how well it performs on unseen data",
       True, None),
      ("They are the same thing", False, None),
      ("Capacity only depends on the dataset size", False, None),
      ("Generalization is fixed by the choice of optimizer alone", False, None)],
     "A high-capacity model can fit complex functions but may generalize poorly without enough data/regularization."),
])

add_items("skill.activation_functions", [
    ("easy", "practice", "What range does the sigmoid activation function output?",
     [("(0, 1)", True, None), ("(-1, 1)", False, None), ("(-inf, inf)", False, None), ("[0, inf)", False, None)],
     "Sigmoid squashes inputs into the open interval (0, 1)."),
    ("medium", "practice", "What is a key advantage of ReLU over sigmoid in hidden layers of deep networks?",
     [("It reduces (but doesn't eliminate) vanishing gradients for positive inputs", True, None),
      ("It has no drawbacks and should replace sigmoid everywhere, including output layers",
       False, "misc.relu_always_better"),
      ("It always outputs values between 0 and 1", False, "misc.relu_always_better"),
      ("It removes the need for a loss function", False, None)],
     "ReLU's gradient is 1 for positive inputs, easing vanishing gradients versus sigmoid's saturating regions; "
     "ReLU is not a universal replacement, e.g. it isn't used to produce output probabilities."),
    ("medium", "practice", "Which activation function is typically used in the output layer for multi-class "
     "classification to produce a probability distribution?",
     [("Softmax", True, None), ("ReLU", False, "misc.relu_always_better"), ("Linear", False, None),
      ("Tanh", False, None)],
     "Softmax converts logits into a normalized probability distribution over classes."),
    ("hard", "probe", "What problem can occur when many ReLU units receive consistently negative input?",
     [("They can become 'dead', always outputting zero and never recovering",
       True, None),
      ("They saturate near 1, just like sigmoid", False, None),
      ("They cause the loss function to become negative", False, None),
      ("They stop the optimizer from updating any weights in the network", False, None)],
     "Persistently negative pre-activations give ReLU zero gradient, a failure mode called 'dying ReLU'."),
])

add_items("skill.backpropagation", [
    ("medium", "practice", "Backpropagation computes gradients of the loss with respect to weights primarily by:",
     [("Applying the chain rule to propagate gradients backward through the computation graph", True,
       "misc.chain_rule_sum"),
      ("Summing the loss gradient independently at each layer with no dependence on other layers", False,
       "misc.backprop_local_gradient_only"),
      ("Randomly perturbing weights and measuring the resulting loss change", False, None),
      ("Directly solving a closed-form equation for the optimal weights", False, None)],
     "Backprop is the chain rule applied systematically backward through the network's computation graph."),
    ("medium", "practice", "During backpropagation, the gradient at a hidden layer depends on:",
     [("The gradients flowing back from all layers downstream of it, multiplied through by local derivatives",
       True, "misc.backprop_local_gradient_only"),
      ("Only that layer's own weights and activation, independent of later layers", False,
       "misc.backprop_local_gradient_only"),
      ("Only the very first layer's gradient", False, None),
      ("The learning rate alone", False, None)],
     "Each layer's gradient is the chain-rule product of local derivatives and everything downstream."),
    ("medium", "practice", "If layer 2's output feeds into layer 3, and we're computing d(Loss)/d(layer2_weights), "
     "the chain rule requires us to:",
     [("Multiply the local layer-2 derivative by the gradient already backpropagated from layer 3", True,
       "misc.chain_rule_sum"),
      ("Add the local layer-2 derivative to the gradient from layer 3", False, "misc.chain_rule_sum"),
      ("Ignore layer 3's gradient entirely", False, "misc.backprop_local_gradient_only"),
      ("Recompute the forward pass from scratch for each weight", False, None)],
     "Chain rule composes derivatives across layers by multiplication, propagating the upstream gradient backward."),
    ("hard", "practice", "In backprop, what does the 'local gradient' at a node get multiplied by before being "
     "passed further back?",
     [("The upstream gradient flowing in from the node(s) it feeds into", True, "misc.chain_rule_sum"),
      ("Nothing — local gradients are used as-is with no upstream term", False, "misc.backprop_local_gradient_only"),
      ("The learning rate", False, None),
      ("The batch size", False, None)],
     "Each node's local derivative is multiplied by the upstream gradient per the chain rule (backprop = "
     "repeated chain-rule application, not per-layer addition)."),
    ("hard", "probe", "Which prerequisite concept is most directly required to derive the backpropagation "
     "update rule for a hidden layer?",
     [("The chain rule for derivatives of composite functions", True, None),
      ("Matrix inversion", False, None),
      ("The central limit theorem", False, None),
      ("Big-O complexity analysis", False, None)],
     "Backpropagation is a systematic application of the chain rule to a layered computation graph."),
    ("hard", "resolution-check", "A network's loss stops decreasing early in training even though gradients are "
     "computed correctly. Which is the most likely explanation tied to backpropagation mechanics rather than "
     "data?",
     [("Gradients are vanishing as they are multiplied back through many layers", True, None),
      ("The chain rule no longer applies once training starts", False, None),
      ("Backpropagation only works for the first epoch", False, None),
      ("The loss function has no derivative", False, None)],
     "Repeated multiplication of small local gradients through depth can shrink gradients toward zero "
     "(vanishing gradients)."),
])

add_items("skill.training_neural_networks", [
    ("easy", "practice", "What is one epoch in neural network training?",
     [("One full pass through the entire training dataset", True, None),
      ("One single weight update", False, None),
      ("One evaluation on the test set", False, None),
      ("The final trained model", False, None)],
     "An epoch is one complete pass over the training data."),
    ("easy", "practice", "What does a 'batch size' control during training?",
     [("How many training examples are used to compute each gradient update", True, None),
      ("How many epochs the model trains for", False, None),
      ("The number of layers in the network", False, None),
      ("The final test accuracy directly", False, None)],
     "Batch size is the number of examples averaged over for one gradient step."),
    ("medium", "practice", "What are the four steps of a standard PyTorch/Keras-style training loop iteration?",
     [("Forward pass, compute loss, backward pass, optimizer step", True, None),
      ("Backward pass, forward pass, save model, evaluate", False, None),
      ("Load data, save model, forward pass, done", False, None),
      ("Compute loss, save checkpoint, restart, repeat", False, None)],
     "Standard loop: forward -> loss -> backward (gradients) -> optimizer.step() (update weights)."),
    ("medium", "resolution-check", "Training loss decreases steadily then suddenly plateaus at a high value. "
     "Which explanation is a mechanics-level issue rather than 'the model already converged optimally'?",
     [("Gradients may be vanishing through the network's depth, stalling learning", True,
       "misc.vanishing_gradient_confusion"),
      ("A flat loss curve always means optimal convergence has been reached", False,
       "misc.vanishing_gradient_confusion"),
      ("The dataset has too many examples", False, None),
      ("PyTorch stops training automatically after convergence", False, None)],
     "A stalled loss can indicate vanishing/exploding gradients or a learning-rate issue, not necessarily "
     "true convergence — this must be diagnosed, not assumed."),
    ("hard", "practice", "Why is it important to call optimizer.zero_grad() (or equivalent) before each "
     "backward pass?",
     [("Gradients accumulate by default, so stale gradients from the previous step would otherwise add in",
       True, None),
      ("It resets the model's weights to their initial values", False, None),
      ("It is only needed once at the very start of training", False, None),
      ("It changes the loss function being used", False, None)],
     "Without clearing, gradients from prior steps accumulate into the current step's gradient."),
    ("hard", "probe", "A model trains well on the training set but its validation loss starts rising after "
     "several epochs while training loss keeps falling. What is the most direct diagnosis?",
     [("Overfitting — the model is fitting training-set noise rather than generalizable patterns", True, None),
      ("The chain rule has stopped applying", False, None),
      ("The batch size is too large to compute gradients", False, None),
      ("The activation function has no gradient", False, None)],
     "A widening train/validation gap is the classic overfitting signature."),
])

add_items("skill.gradient_descent_variants", [
    ("easy", "practice", "What does the learning rate control in gradient descent?",
     [("The size of the step taken in the direction of the negative gradient", True, None),
      ("The number of layers updated", False, None),
      ("The batch size used per step", False, None),
      ("The final test accuracy directly", False, None)],
     "Learning rate scales how far weights move along the negative gradient each step."),
    ("medium", "practice", "What is the key difference between stochastic gradient descent (SGD) and full-batch "
     "gradient descent?",
     [("SGD estimates the gradient from one (or a few) examples per step, introducing noise vs. the full-batch "
       "gradient", True, "misc.sgd_same_as_gd"),
      ("SGD and full-batch gradient descent always follow identical trajectories", False, "misc.sgd_same_as_gd"),
      ("SGD does not use gradients at all", False, None),
      ("Full-batch gradient descent cannot be used for neural networks", False, None)],
     "SGD's per-step gradient is a noisy estimate of the true full-batch gradient, not identical to it."),
    ("medium", "practice", "What does momentum add to a gradient descent update?",
     [("A running average of past gradients, smoothing the update direction", True, None),
      ("A random perturbation to escape all local minima guaranteed", False, None),
      ("An extra hidden layer to the network", False, None),
      ("A second loss function", False, None)],
     "Momentum accumulates a velocity term from past gradients to smooth/accelerate descent."),
    ("hard", "practice", "Why might the Adam optimizer converge faster than plain SGD on many deep learning "
     "problems?",
     [("It adapts per-parameter learning rates using estimates of first and second gradient moments", True, None),
      ("It always uses a larger fixed learning rate than SGD", False, None),
      ("It ignores gradients after the first epoch", False, None),
      ("It replaces backpropagation with a different rule for computing gradients", False, None)],
     "Adam maintains per-parameter adaptive learning rates from moving averages of gradients and their squares."),
])

add_items("skill.overfitting_regularization", [
    ("easy", "practice", "What does 'overfitting' mean?",
     [("A model fits the training data very well but generalizes poorly to new data", True, None),
      ("A model performs poorly on both training and test data", False, None),
      ("A model that trains too slowly", False, None),
      ("A model with too few parameters to learn anything", False, None)],
     "Overfitting is high training performance with poor generalization to unseen data."),
    ("medium", "practice", "Can overfitting occur even with a very large training dataset?",
     [("Yes — it depends on model capacity relative to the signal/complexity in the data, not dataset size alone",
       True, "misc.overfitting_is_just_memorizing"),
      ("No — overfitting is only possible with small datasets", False, "misc.overfitting_is_just_memorizing"),
      ("No — more data always eliminates overfitting completely", False, "misc.overfitting_is_just_memorizing"),
      ("Only if the model has zero parameters", False, None)],
     "A sufficiently high-capacity model can still overfit even large datasets; data size reduces but doesn't "
     "categorically prevent overfitting."),
    ("medium", "practice", "What is the general effect of L2 regularization on model weights?",
     [("It penalizes large weight magnitudes, encouraging smaller, smoother weights", True, None),
      ("It forces all weights to exactly zero", False, None),
      ("It increases model capacity", False, None),
      ("It removes the need for a validation set", False, None)],
     "L2 regularization adds a penalty proportional to the squared weight magnitude."),
    ("hard", "practice", "What does the bias-variance tradeoff describe?",
     [("The balance between a model being too simple (high bias) vs. too sensitive to training noise "
       "(high variance)", True, None),
      ("The tradeoff between training speed and inference speed", False, None),
      ("The choice between two different loss functions", False, None),
      ("The number of GPUs used for training", False, None)],
     "High bias underfits; high variance overfits — regularization and model complexity trade off between them."),
])

add_items("skill.cross_validation", [
    ("easy", "practice", "What is the main purpose of k-fold cross-validation?",
     [("To get a more robust estimate of a model's generalization performance", True, None),
      ("To automatically fix an overfitting model without any other changes", False, "misc.cv_prevents_overfitting"),
      ("To increase the size of the training dataset", False, None),
      ("To replace the need for a test set entirely in all cases", False, None)],
     "Cross-validation estimates generalization performance by rotating which fold is held out; it detects, "
     "but does not by itself fix, overfitting."),
    ("medium", "practice", "In 5-fold cross-validation, how many times is the model trained?",
     [("5 times, each time on a different 4/5 split with the remaining 1/5 held out", True, None),
      ("Once, on the entire dataset", False, None),
      ("25 times", False, None),
      ("It depends only on the number of features", False, None)],
     "Each of the 5 folds takes a turn as the held-out validation set."),
    ("hard", "resolution-check", "A model shows strong cross-validation scores but still overfits badly once "
     "deployed on truly new data. What does this most likely indicate?",
     [("The CV folds weren't representative of the deployment distribution, or CV was leaking information",
       True, "misc.cv_prevents_overfitting"),
      ("Cross-validation guarantees deployment performance and this shouldn't be possible", False,
       "misc.cv_prevents_overfitting"),
      ("The model has too few parameters", False, None),
      ("The loss function is broken", False, None)],
     "CV estimates generalization under its own sampling assumptions; it doesn't guarantee real-world "
     "performance if the deployment distribution differs or there's leakage."),
])

add_items("skill.sql_joins", [
    ("easy", "practice", "What does an INNER JOIN return?",
     [("Only rows that have matching values in both tables", True, "misc.sql_inner_join_default_keeps_all"),
      ("All rows from both tables regardless of a match", False, "misc.sql_inner_join_default_keeps_all"),
      ("Only rows from the left table", False, None),
      ("Only rows with NULL values", False, None)],
     "INNER JOIN keeps only rows where the join condition matches in both tables."),
    ("easy", "practice", "What does a LEFT JOIN return that an INNER JOIN would not?",
     [("All rows from the left table, with NULLs for unmatched right-table columns", True,
       "misc.left_join_symmetric"),
      ("Only rows that match in both tables", False, "misc.left_join_symmetric"),
      ("All rows from the right table only", False, None),
      ("Rows sorted alphabetically", False, None)],
     "LEFT JOIN preserves every row from the left table even without a match on the right."),
    ("medium", "practice", "Table `orders` has a row with `customer_id = 7` that does not exist in `customers`. "
     "What happens with `orders INNER JOIN customers ON orders.customer_id = customers.id`?",
     [("That order row is excluded from the result", True, "misc.sql_inner_join_default_keeps_all"),
      ("That order row appears with NULL customer columns", False, "misc.sql_inner_join_default_keeps_all"),
      ("The query fails with an error", False, None),
      ("It appears twice", False, None)],
     "INNER JOIN drops rows without a match on either side."),
    ("medium", "practice", "With the same tables, what changes if you use `orders LEFT JOIN customers ON "
     "orders.customer_id = customers.id` instead?",
     [("The unmatched order row is kept, with NULLs for the customer columns", True,
       "misc.sql_inner_join_default_keeps_all"),
      ("The unmatched order row is still excluded, same as INNER JOIN", False, "misc.left_join_symmetric"),
      ("Only customers with no orders are returned", False, None),
      ("It behaves identically to a RIGHT JOIN on the same tables", False, "misc.left_join_symmetric")],
     "LEFT JOIN preserves left-table rows regardless of a match, unlike INNER JOIN."),
    ("hard", "practice", "If `A LEFT JOIN B` and `A RIGHT JOIN B` are run on the same two tables in the same "
     "order, when do they return the same result set?",
     [("Only when every row in A matches a row in B and vice versa (no unmatched rows on either side)", True,
       "misc.left_join_symmetric"),
      ("Always — LEFT and RIGHT JOIN are interchangeable", False, "misc.left_join_symmetric"),
      ("Never under any circumstance", False, None),
      ("Only when the tables have the same number of columns", False, None)],
     "LEFT and RIGHT JOIN only coincide when there are no unmatched rows on either side to reveal the "
     "row-preservation difference."),
    ("hard", "probe", "Why can adding an INNER JOIN to a query silently reduce the row count compared to "
     "querying a single table?",
     [("Rows without a matching key in the joined table are dropped from the result", True,
       "misc.sql_inner_join_default_keeps_all"),
      ("INNER JOIN always increases row count", False, None),
      ("JOIN only affects columns, never row count", False, None),
      ("SQL guarantees the same row count regardless of join type", False, None)],
     "INNER JOIN filters out rows lacking a match, which is a common source of unexpectedly 'missing' data."),
])

add_items("skill.hypothesis_testing", [
    ("easy", "practice", "In hypothesis testing, what does the null hypothesis (H0) typically represent?",
     [("The default assumption of no effect or no difference", True, None),
      ("The hypothesis the researcher wants to prove true", False, None),
      ("A guaranteed true statement", False, None),
      ("The sample mean", False, None)],
     "H0 is the default/no-effect baseline that a test tries to find evidence against."),
    ("medium", "practice", "What does a p-value of 0.03 mean in a hypothesis test?",
     [("Assuming H0 is true, there's a 3% chance of observing data this extreme or more", True,
       "misc.pvalue_probability_null_true"),
      ("There is a 3% probability that H0 is true", False, "misc.pvalue_probability_null_true"),
      ("There is a 97% probability that the alternative hypothesis is true", False,
       "misc.pvalue_probability_null_true"),
      ("The effect size is 0.03", False, None)],
     "A p-value is P(data this extreme | H0 true), not P(H0 true | data)."),
    ("medium", "practice", "A 95% confidence interval for a mean is [10.2, 12.8]. What is the correct "
     "interpretation?",
     [("If we repeated this sampling process many times, about 95% of such intervals would contain the true "
       "mean", True, "misc.confidence_interval_contains_true_value_95pct"),
      ("There is a 95% chance the true mean lies between 10.2 and 12.8 for this specific interval", False,
       "misc.confidence_interval_contains_true_value_95pct"),
      ("95% of the data falls between 10.2 and 12.8", False, None),
      ("The true mean is definitely between 10.2 and 12.8", False, None)],
     "Confidence level describes the long-run coverage of the procedure, not a probability statement about "
     "one already-computed interval."),
    ("hard", "resolution-check", "A colleague says 'our p-value was 0.01, so there's a 99% chance our new "
     "feature really works.' What's wrong with this statement?",
     [("It misinterprets the p-value as the probability the alternative hypothesis is true", True,
       "misc.pvalue_probability_null_true"),
      ("Nothing — this is a correct interpretation of p = 0.01", False, "misc.pvalue_probability_null_true"),
      ("p-values can never be below 0.05", False, None),
      ("The statement is about confidence intervals, not p-values", False, None)],
     "A p-value doesn't quantify the probability that a hypothesis is true; it's a statement about the data "
     "given the null."),
])

add_items("skill.recursion", [
    ("easy", "practice", "What two parts does every correct recursive function need?",
     [("A base case and a recursive case that moves toward it", True, "misc.recursion_no_base_case_needed"),
      ("Only a recursive case; the function stops automatically when inputs shrink", False,
       "misc.recursion_no_base_case_needed"),
      ("A loop and a counter", False, None),
      ("Two return statements only", False, None)],
     "Without an explicit base case, a recursive function can recurse forever even if inputs appear to shrink."),
    ("medium", "practice", "What happens if a recursive function is missing its base case?",
     [("It can recurse indefinitely, eventually causing a stack overflow", True,
       "misc.recursion_no_base_case_needed"),
      ("Python automatically stops it after one call", False, "misc.recursion_no_base_case_needed"),
      ("It becomes an iterative loop instead", False, None),
      ("It always returns None safely", False, None)],
     "Missing base cases are a classic cause of infinite recursion and stack overflow errors."),
    ("medium", "practice", "What is the base case of a recursive factorial function `fact(n)`?",
     [("fact(0) = 1 (or fact(1) = 1)", True, None),
      ("fact(n) = n * fact(n-1) for all n", False, "misc.recursion_no_base_case_needed"),
      ("There is no base case needed for factorial", False, "misc.recursion_no_base_case_needed"),
      ("fact(n) = n", False, None)],
     "fact(0)=1 stops the recursion; every other call reduces n toward that base case."),
    ("hard", "practice", "Why does `def f(n): return f(n-1)` (with no base case) eventually crash?",
     [("Each call adds a new stack frame with no terminating condition, exhausting the call stack", True,
       "misc.recursion_no_base_case_needed"),
      ("Python detects the missing base case and returns 0", False, "misc.recursion_no_base_case_needed"),
      ("It runs forever without crashing", False, None),
      ("It only fails for negative n", False, None)],
     "Without a base case the recursion never stops, exhausting the call stack (RecursionError/StackOverflow)."),
])

add_items("skill.big_o", [
    ("easy", "practice", "What does O(n) describe about an algorithm?",
     [("Its running time grows linearly with input size n, as an upper bound", True, None),
      ("It always takes exactly n seconds to run", False, None),
      ("It only describes worst-case runtime and nothing else", False, "misc.big_o_worst_case_only_matters"),
      ("It measures memory use only, never time", False, None)],
     "Big-O gives an asymptotic upper bound on growth rate, applicable to time or space."),
    ("medium", "practice", "Binary search on a sorted array of size n has what time complexity?",
     [("O(log n)", True, None), ("O(n)", False, None), ("O(n log n)", False, None), ("O(1)", False, None)],
     "Binary search halves the search space each step, giving logarithmic time."),
    ("hard", "practice", "Is it accurate to say 'Big-O notation always describes an algorithm's worst-case "
     "runtime'?",
     [("Not necessarily — O/Θ/Ω describe upper/tight/lower growth bounds and can be applied to best-, "
       "average-, or worst-case analyses", True, "misc.big_o_worst_case_only_matters"),
      ("Yes, Big-O and worst-case are always the same thing", False, "misc.big_o_worst_case_only_matters"),
      ("No, Big-O only applies to average-case analysis", False, None),
      ("Big-O only measures space complexity, never time", False, None)],
     "Big-O bounds growth rate; which case (best/average/worst) it's applied to is a separate, orthogonal "
     "choice made by the analysis."),
])

add_items("skill.rest_api_design", [
    ("easy", "practice", "Which HTTP method is conventionally used to retrieve a resource without side "
     "effects?",
     [("GET", True, "misc.rest_get_can_mutate"), ("POST", False, None), ("DELETE", False, None),
      ("PUT", False, None)],
     "GET is expected to be safe (no side effects) and cacheable/idempotent."),
    ("medium", "practice", "Is it acceptable REST design to delete a resource via a GET request, e.g. "
     "`GET /items/5/delete`?",
     [("No — GET must be safe/side-effect-free; deletion should use DELETE (or POST)", True,
       "misc.rest_get_can_mutate"),
      ("Yes — as long as the endpoint works, the HTTP method doesn't matter", False,
       "misc.rest_get_can_mutate"),
      ("Yes, but only for admin users", False, "misc.rest_get_can_mutate"),
      ("No — GET requests are not allowed to have URL parameters", False, None)],
     "Mutating state via GET breaks caching, prefetching and crawler safety assumptions that depend on GET "
     "being side-effect-free."),
    ("medium", "practice", "What HTTP status code should a successful POST that creates a new resource "
     "typically return?",
     [("201 Created", True, None), ("200 OK only, never 201", False, None), ("404 Not Found", False, None),
      ("500 Internal Server Error", False, None)],
     "201 Created signals that a new resource was successfully created, often with a Location header."),
    ("hard", "probe", "A client caches GET responses aggressively. Why does this make it especially important "
     "that GET endpoints never mutate state?",
     [("A cached GET response could be reused instead of the request actually reaching the server, so "
       "expected side effects may silently not happen (or happen unexpectedly)", True, "misc.rest_get_can_mutate"),
      ("Caching has nothing to do with which HTTP method is used", False, None),
      ("GET requests cannot be cached at all", False, None),
      ("Mutating GET requests always bypass the cache automatically", False, "misc.rest_get_can_mutate")],
     "HTTP infrastructure assumes GET is safe and may cache/replay/prefetch it, which is dangerous if GET "
     "has side effects."),
])

add_items("skill.authentication_authorization", [
    ("easy", "practice", "What is the difference between authentication and authorization?",
     [("Authentication verifies who you are; authorization determines what you're allowed to do", True, None),
      ("They are the same thing", False, None),
      ("Authorization happens before authentication always", False, None),
      ("Authentication is only relevant for admin users", False, None)],
     "Authentication = identity verification; authorization = permission checking."),
    ("medium", "practice", "Is the payload of a standard (unencrypted) JWT safe to store secret data in?",
     [("No — the payload is base64-encoded and signed, not encrypted, so it's readable by anyone who has "
       "the token", True, "misc.jwt_is_encrypted"),
      ("Yes — JWTs are encrypted by default, so secrets are safe inside them", False, "misc.jwt_is_encrypted"),
      ("Yes, as long as HTTPS is used for transport", False, "misc.jwt_is_encrypted"),
      ("No, because JWTs cannot contain custom claims", False, None)],
     "A standard JWT is signed (tamper-evident) but not encrypted; anyone holding it can decode the payload."),
    ("medium", "practice", "What does a JWT signature actually guarantee?",
     [("That the token's claims haven't been tampered with since it was signed", True, "misc.jwt_is_encrypted"),
      ("That the token's contents are hidden from the holder", False, "misc.jwt_is_encrypted"),
      ("That the token never expires", False, None),
      ("That the user's password is embedded securely", False, None)],
     "The signature provides integrity/authenticity, not confidentiality of the payload."),
    ("hard", "probe", "Why is storing a user's plaintext password inside a JWT claim a serious security "
     "mistake?",
     [("Because the JWT payload is only base64-encoded, not encrypted, so anyone holding the token can "
       "trivially decode the password", True, "misc.jwt_is_encrypted"),
      ("Because JWTs cannot store strings", False, None),
      ("It isn't a mistake as long as the signature is valid", False, "misc.jwt_is_encrypted"),
      ("Because JWTs automatically expire after one use", False, None)],
     "Signing (JWT default) is not the same as encryption; sensitive data in the payload is exposed."),
])

add_items("skill.testing_fundamentals", [
    ("easy", "practice", "What is the main purpose of a unit test?",
     [("To verify that a specific, small piece of code behaves as expected in isolation", True, None),
      ("To test the entire deployed system end-to-end", False, None),
      ("To measure code execution speed only", False, None),
      ("To replace the need for code review", False, None)],
     "Unit tests target small, isolated units of behavior (e.g. a function)."),
    ("medium", "practice", "Does a fully passing unit test suite guarantee a codebase has no bugs?",
     [("No — it only shows the specifically tested behaviors work as expected; untested paths can still "
       "have bugs", True, "misc.unit_tests_prove_no_bugs"),
      ("Yes — 100% passing tests guarantees zero bugs anywhere in the code", False,
       "misc.unit_tests_prove_no_bugs"),
      ("Yes, as long as there are more than 10 tests", False, "misc.unit_tests_prove_no_bugs"),
      ("No — unit tests can never catch any real bugs", False, None)],
     "Tests only cover the behaviors/paths they actually exercise; passing tests is evidence, not proof, of "
     "correctness."),
    ("hard", "resolution-check", "A team ships a feature because 'all tests are green', and a production "
     "bug appears in an edge case with no test coverage. What does this best illustrate?",
     [("Passing tests only prove the tested behaviors work — untested edge cases remain unverified", True,
       "misc.unit_tests_prove_no_bugs"),
      ("The testing framework must be broken", False, None),
      ("Green tests should have made this impossible", False, "misc.unit_tests_prove_no_bugs"),
      ("Production bugs can never happen if unit tests pass", False, "misc.unit_tests_prove_no_bugs")],
     "This is a textbook case of confusing 'tests pass' with 'code is bug-free' — coverage gaps hide bugs."),
])

add_items("skill.docker", [
    ("easy", "practice", "What is the difference between a Docker image and a Docker container?",
     [("An image is a read-only template; a container is a running (or stopped) instance created from it",
       True, "misc.docker_image_is_running_container"),
      ("They are the same thing with different names", False, "misc.docker_image_is_running_container"),
      ("An image only exists while a container is running", False, "misc.docker_image_is_running_container"),
      ("A container is required before an image can be built", False, None)],
     "The image is the template on disk; containers are runtime instances created from it and can be "
     "started/stopped/removed independently of the image."),
    ("medium", "practice", "If you run `docker stop mycontainer`, what happens to the image it was created "
     "from?",
     [("Nothing — the image is untouched and can be used to start new containers", True,
       "misc.docker_image_is_running_container"),
      ("The image is deleted along with the container", False, "misc.docker_image_is_running_container"),
      ("The image becomes read-write", False, None),
      ("A new image is automatically created", False, None)],
     "Stopping (or even removing) a container does not delete the image it was built from."),
    ("hard", "probe", "Why can you run multiple containers from the same Docker image at the same time?",
     [("Because the image is an immutable template, and each container gets its own isolated writable "
       "layer/runtime state", True, "misc.docker_image_is_running_container"),
      ("You cannot — an image can only back one container at a time", False,
       "misc.docker_image_is_running_container"),
      ("Because containers share a single filesystem with no isolation", False, None),
      ("Because Docker automatically merges containers together", False, None)],
     "Images are read-only templates; each container instance is isolated, which is exactly why one image "
     "can back many concurrent containers."),
])

add_items("skill.relational_modeling", [
    ("easy", "practice", "What is the goal of normalizing a relational schema?",
     [("Reducing data redundancy and avoiding update anomalies", True, None),
      ("Always minimizing the number of queries needed", False, None),
      ("Guaranteeing the fastest possible query performance", False, "misc.normalization_removes_all_duplication"),
      ("Storing all data in a single table", False, None)],
     "Normalization organizes data to reduce redundancy and anomalies, not to directly maximize speed."),
    ("medium", "practice", "Does fully normalizing a schema (3NF and beyond) always improve query "
     "performance?",
     [("No — heavy normalization can require many joins, which can hurt read performance for reporting "
       "workloads", True, "misc.normalization_removes_all_duplication"),
      ("Yes — more normalization always means faster queries", False,
       "misc.normalization_removes_all_duplication"),
      ("Yes, because normalized tables are always smaller", False,
       "misc.normalization_removes_all_duplication"),
      ("Normalization has no effect on performance at all", False, None)],
     "Normalization optimizes for update integrity, not necessarily read speed; denormalization is a common "
     "tradeoff for reporting/analytics workloads."),
    ("hard", "resolution-check", "A reporting dashboard query joins 8 normalized tables and is slow. What's "
     "the most defensible next step, given normalization tradeoffs?",
     [("Consider a denormalized read model / materialized view for this reporting path, while keeping the "
       "normalized schema for writes", True, "misc.normalization_removes_all_duplication"),
      ("Normalize the schema even further, since more normalization always helps performance", False,
       "misc.normalization_removes_all_duplication"),
      ("Nothing can be done — normalized schemas can never be optimized for reads", False, None),
      ("Delete the extra tables entirely", False, None)],
     "A common pattern is normalized write models plus denormalized read models for reporting."),
])

add_items("skill.python", [
    ("easy", "practice", "What does `len([1, 2, 3])` return in Python?",
     [("3", True, None), ("2", False, None), ("[1, 2, 3]", False, None), ("Error", False, None)],
     "len() returns the number of elements in the list."),
    ("easy", "practice", "Which keyword defines a function in Python?",
     [("def", True, None), ("function", False, None), ("func", False, None), ("lambda only", False, None)],
     "`def` introduces a named function definition."),
    ("medium", "practice", "What is the output of `type([1, 2])` in Python?",
     [("<class 'list'>", True, None), ("<class 'tuple'>", False, None), ("<class 'array'>", False, None),
      ("<class 'dict'>", False, None)],
     "Square brackets create a list, whose type is `list`."),
    ("medium", "practice", "What does a Python list comprehension `[x*2 for x in range(3)]` evaluate to?",
     [("[0, 2, 4]", True, None), ("[1, 2, 3]", False, None), ("[0, 1, 2]", False, None), ("[2, 4, 6]", False, None)],
     "range(3) yields 0,1,2; doubling each gives 0,2,4."),
])

add_items("skill.sql_fundamentals", [
    ("easy", "practice", "Which SQL clause filters rows before aggregation?",
     [("WHERE", True, None), ("HAVING", False, None), ("GROUP BY", False, None), ("ORDER BY", False, None)],
     "WHERE filters individual rows before any GROUP BY aggregation happens."),
    ("easy", "practice", "What does `SELECT * FROM users;` return?",
     [("All columns for every row in the users table", True, None),
      ("Only the first row of the users table", False, None),
      ("The number of rows in the users table", False, None),
      ("An error, since * is invalid", False, None)],
     "`SELECT *` selects all columns; with no WHERE clause, all rows are returned."),
    ("medium", "practice", "Which clause is used to filter groups after a GROUP BY aggregation?",
     [("HAVING", True, None), ("WHERE", False, None), ("FILTER", False, None), ("LIMIT", False, None)],
     "HAVING filters on aggregated results, unlike WHERE which filters raw rows."),
    ("medium", "practice", "What does `ORDER BY price DESC LIMIT 1` return?",
     [("The single row with the highest price", True, None),
      ("The single row with the lowest price", False, None),
      ("All rows sorted by price", False, None),
      ("An error", False, None)],
     "DESC sorts highest-first; LIMIT 1 takes just the top row."),
])

add_items("skill.pandas", [
    ("easy", "practice", "What pandas method reads a CSV file into a DataFrame?",
     [("pd.read_csv()", True, None), ("pd.load_csv()", False, None), ("pd.open_csv()", False, None),
      ("pd.import_csv()", False, None)],
     "pandas.read_csv() is the standard way to load CSV data."),
    ("medium", "practice", "What does `df.groupby('category')['sales'].sum()` compute?",
     [("The total sales for each distinct category", True, None),
      ("The average sales across the whole DataFrame", False, None),
      ("The number of categories", False, None),
      ("Sales sorted alphabetically by category", False, None)],
     "groupby + sum aggregates the sales column within each category group."),
    ("hard", "practice", "What is the key difference between `df.loc[]` and `df.iloc[]`?",
     [("loc selects by label, iloc selects by integer position", True, None),
      ("They are interchangeable in every case", False, None),
      ("iloc selects by label, loc selects by position", False, None),
      ("loc only works on Series, not DataFrames", False, None)],
     "loc is label-based indexing; iloc is purely positional (integer-based) indexing."),
])

add_items("skill.supervised_learning", [
    ("easy", "practice", "What defines a supervised learning problem?",
     [("The training data includes labeled input-output pairs", True, None),
      ("The data has no labels at all", False, None),
      ("The model must be a neural network", False, None),
      ("There is no training phase", False, None)],
     "Supervised learning trains on labeled (input, target) pairs."),
    ("easy", "practice", "Which task is a classification problem?",
     [("Predicting whether an email is spam or not spam", True, None),
      ("Predicting a house's exact sale price in dollars", False, None),
      ("Clustering customers into unlabeled segments", False, None),
      ("Reducing the number of features in a dataset", False, None)],
     "Spam/not-spam is a discrete-label classification task."),
    ("medium", "practice", "Which task is a regression problem?",
     [("Predicting a continuous numeric value like house price", True, None),
      ("Predicting a discrete category like 'cat' vs 'dog'", False, None),
      ("Grouping unlabeled data points into clusters", False, None),
      ("Reducing dimensionality via PCA", False, None)],
     "Regression predicts continuous numeric outputs."),
    ("hard", "practice", "Why is a held-out test set necessary even after using cross-validation during "
     "model selection?",
     [("Repeated model-selection decisions based on CV can still overfit to the validation folds; a final "
       "untouched test set gives an unbiased estimate", True, None),
      ("Test sets are only needed for classification, not regression", False, None),
      ("Cross-validation makes a separate test set unnecessary in every case", False, None),
      ("Test sets replace the need for a training set", False, None)],
     "Model/hyperparameter selection via CV can indirectly overfit the validation folds, so a final held-out "
     "test set is kept for an unbiased performance estimate."),
])

add_items("skill.ml_fundamentals", [
    ("easy", "practice", "What is 'training' a machine learning model?",
     [("Adjusting model parameters using data so predictions improve on a defined objective", True, None),
      ("Manually writing rules for every possible input", False, None),
      ("Only evaluating a model on a test set", False, None),
      ("Deploying a model to production", False, None)],
     "Training fits parameters to data by optimizing a loss/objective."),
    ("medium", "practice", "Why is a train/test split used when building an ML model?",
     [("To estimate how well the model generalizes to data it hasn't seen", True, None),
      ("To make the training process run faster", False, None),
      ("Because models cannot be trained on the full dataset", False, None),
      ("To remove the need for any evaluation metric", False, None)],
     "The test set approximates unseen, real-world data to check generalization."),
    ("hard", "practice", "What is the difference between a model's parameters and its hyperparameters?",
     [("Parameters are learned from data during training; hyperparameters are set before training and "
       "control the learning process", True, None),
      ("They are the same thing", False, None),
      ("Hyperparameters are learned, parameters are fixed by the user", False, None),
      ("Parameters only exist in deep learning models", False, None)],
     "E.g. weights are parameters (learned); learning rate is a hyperparameter (chosen)."),
])

ITEM_IDS = {i["item_id"] for i in ITEMS}


# --------------------------------------------------------------------------
# 7. DEMO DATASET — design doc §38.1 persona "Asha", primary demo path
#    Chain Rule -> Backpropagation -> Training Neural Networks (PyTorch)
# --------------------------------------------------------------------------

DEMO_LEARNER = {
    "learner_id": "demo-learner-asha",
    "user_id": "demo-user-asha",
    "name": "Asha",
    "persona_note": "Third-year AIML student. Design doc §38.1 demo persona.",
    "target_role_id": "role.ml_engineer",
    "career_goal": "Become a Machine Learning Engineer working on computer vision systems.",
    "experience_summary": "Third-year AI/ML undergraduate; coursework in programming and calculus; "
                           "one independent object-detection project.",
    "weekly_hours": 5,
    "preferences": {
        "modality_order": ["do", "watch", "read"],
        "language": "en",
        "session_length_minutes_max": 60,
    },
    "constraints": {
        "fixed_days_off": ["Sunday"],
    },
}

DEMO_RESUME_MD = """# Asha — Resume (demo seed)

## Education
B.Tech, Artificial Intelligence & Machine Learning (3rd year, in progress)

## Skills
Python, PyTorch (basic), OpenCV, Calculus (coursework)

## Projects
**Real-time Object Detection with YOLOv8** — Independent project
Built and trained a YOLOv8-based object detector for a custom dataset of five
object classes. Implemented the data pipeline with OpenCV for frame capture
and preprocessing, trained the model with PyTorch, and evaluated it with
precision/recall on a held-out validation split. Deployed a demo inference
script that runs on a laptop webcam feed in real time.

Public repository: https://github.com/demo-asha/yolov8-object-detection
(placeholder demo URL — replace with a real seeded repo before a live demo)

## Coursework
- Calculus I & II
- Linear Algebra
- Data Structures and Algorithms
- Introduction to Machine Learning
"""

# Skill states mirror the worked example in design §13.4.
DEMO_LEARNER_STATE = {
    "learner_id": "demo-learner-asha",
    "graph_version": GRAPH_VERSION,
    "skill_states": [
        {
            "skill_id": "skill.python", "status_for_role": "MET", "target_level": 2,
            "mastery": {"alpha": 6.0, "beta": 2.0, "estimate": 0.75, "band": "Proficient", "confidence": "medium",
                        "n_obs": 0},
            "tier_max": "E2", "claims": ["Python listed on resume"],
            "evidence": [{"evidence_id": "ev.asha.python.github", "tier": "E2",
                          "source_type": "github_repo", "note": "Repo languages breakdown: Python 92%."}],
        },
        {
            "skill_id": "skill.cnn", "status_for_role": "MET", "target_level": 2,
            "mastery": {"alpha": 5.0, "beta": 2.0, "estimate": 0.71, "band": "Developing", "confidence": "medium",
                        "n_obs": 0},
            "tier_max": "E2", "claims": ["OpenCV + YOLOv8 project"],
            "evidence": [{"evidence_id": "ev.asha.cnn.project", "tier": "E2",
                          "source_type": "document", "note": "Resume project description: YOLOv8 detector, "
                          "trained with PyTorch, README + code verified via GitHub."}],
        },
        {
            "skill_id": "skill.object_detection", "status_for_role": "MET", "target_level": 1,
            "mastery": {"alpha": 4.0, "beta": 1.5, "estimate": 0.73, "band": "Developing", "confidence": "medium",
                        "n_obs": 0},
            "tier_max": "E2", "claims": ["YOLOv8 project"],
            "evidence": [{"evidence_id": "ev.asha.objdet.project", "tier": "E2",
                          "source_type": "github_repo", "note": "YOLOv8 object-detection repo, verified."}],
        },
        {
            "skill_id": "skill.opencv", "status_for_role": "MET", "target_level": 1,
            "mastery": {"alpha": 3.0, "beta": 1.0, "estimate": 0.75, "band": "Developing", "confidence": "low",
                        "n_obs": 0},
            "tier_max": "E2", "claims": ["OpenCV listed on resume"],
            "evidence": [{"evidence_id": "ev.asha.opencv.project", "tier": "E2",
                          "source_type": "github_repo", "note": "OpenCV used for frame capture/preprocessing."}],
        },
        {
            "skill_id": "skill.chain_rule", "status_for_role": "UNVERIFIED", "target_level": 2,
            "mastery": {"alpha": 0.5, "beta": 1.0, "estimate": 0.5, "band": "Unknown", "confidence": "low",
                        "n_obs": 0},
            "tier_max": "E0", "claims": ["\"Calculus\" listed in coursework"],
            "evidence": [],
            "note": "Inferred only from the 'Calculus' coursework line item — E0, no direct evidence.",
        },
        {
            "skill_id": "skill.backpropagation", "status_for_role": "UNVERIFIED", "target_level": 2,
            "mastery": {"alpha": 1.0, "beta": 1.5, "estimate": 0.4, "band": "Unknown", "confidence": "low",
                        "n_obs": 0},
            "tier_max": "E1", "claims": ["\"Trained models\" implied by the YOLOv8 project description"],
            "evidence": [{"evidence_id": "ev.asha.backprop.resume", "tier": "E1",
                          "source_type": "document", "note": "Resume prose mentions training the model, but "
                          "does not demonstrate understanding of how training works."}],
            "note": "E1 only (resume prose, no assessment) — cannot satisfy MET at L2 (needs E2/E3).",
        },
        {
            "skill_id": "skill.neural_network_fundamentals", "status_for_role": "UNVERIFIED", "target_level": 2,
            "mastery": {"alpha": 1.0, "beta": 1.0, "estimate": 0.5, "band": "Unknown", "confidence": "low",
                        "n_obs": 0},
            "tier_max": "E1", "claims": ["Implied by PyTorch usage in the YOLOv8 project"],
            "evidence": [{"evidence_id": "ev.asha.nnfund.resume", "tier": "E1",
                          "source_type": "document", "note": "Used PyTorch to train a model; conceptual "
                          "understanding of network fundamentals not directly evidenced."}],
        },
        {
            "skill_id": "skill.training_neural_networks", "status_for_role": "UNVERIFIED", "target_level": 2,
            "mastery": {"alpha": 1.0, "beta": 1.0, "estimate": 0.5, "band": "Unknown", "confidence": "low",
                        "n_obs": 0},
            "tier_max": "E1", "claims": ["YOLOv8 project trained with PyTorch"],
            "evidence": [{"evidence_id": "ev.asha.train.resume", "tier": "E1",
                          "source_type": "document", "note": "Trained a model end-to-end, but backpropagation "
                          "(a hard prerequisite) is itself UNVERIFIED, not MET."}],
            "note": "Would become BLOCKED if backpropagation is later found WEAK/MISSING after the probe.",
        },
        {
            "skill_id": "skill.mlops_fundamentals", "status_for_role": "MISSING", "target_level": 1,
            "mastery": {"alpha": 0.5, "beta": 1.0, "estimate": 0.5, "band": "Unknown", "confidence": "low",
                        "n_obs": 0},
            "tier_max": None, "claims": [], "evidence": [],
            "note": "No claim, no evidence — the first true learning objective per §13.4.",
        },
    ],
    "misconceptions": [],
    "open_audit_flags": [
        {"flag": "claim_evidence_mismatch", "skill_id": "skill.backpropagation",
         "detail": "Trained a model (implies backprop was used) but no direct evidence of understanding it."},
    ],
}

DEMO_SCENARIO = {
    "scenario_id": "demo.asha.ml_engineer.week1",
    "graph_version": GRAPH_VERSION,
    "learner_id": "demo-learner-asha",
    "role_id": "role.ml_engineer",
    "description": "Design doc §38.2 scripted demo flow: resume upload -> gap analysis -> weekly plan -> "
                    "probe/practice -> misconception detection -> reflection -> re-plan -> tutor Q&A.",
    "seeded_graph_path": ["skill.chain_rule", "skill.backpropagation", "skill.training_neural_networks"],
    "seeded_misconception": {
        "misconception_id": "misc.chain_rule_sum",
        "affected_skill": "skill.backpropagation",
        "root_prerequisite": "skill.chain_rule",
    },
    "seeded_item_set": {
        "purpose": "backpropagation assessment with prerequisite block",
        "backpropagation_items": ["item.backpropagation.1", "item.backpropagation.2",
                                   "item.backpropagation.3", "item.backpropagation.4"],
        "chain_rule_prereq_block_items": ["item.chain_rule.3", "item.chain_rule.4"],
        "misconception_tagged_items": ["item.backpropagation.1", "item.backpropagation.3",
                                        "item.backpropagation.4", "item.chain_rule.2",
                                        "item.chain_rule.4", "item.chain_rule.5"],
    },
    "scripted_attempt": {
        "description": "Scripted-wrong-answer button per §38.2 step 8: selects the "
                        "misc.chain_rule_sum-tagged distractor on the misconception-tagged items, and fails "
                        "the chain_rule prerequisite-block items.",
        "answers": [
            {"item_id": "item.backpropagation.1", "chosen_is_key": False,
             "chosen_misconception_id": "misc.chain_rule_sum"},
            {"item_id": "item.backpropagation.2", "chosen_is_key": True, "chosen_misconception_id": None},
            {"item_id": "item.backpropagation.3", "chosen_is_key": False,
             "chosen_misconception_id": "misc.chain_rule_sum"},
            {"item_id": "item.backpropagation.4", "chosen_is_key": False,
             "chosen_misconception_id": "misc.chain_rule_sum"},
            {"item_id": "item.chain_rule.3", "chosen_is_key": False, "chosen_misconception_id": "misc.chain_rule_sum"},
            {"item_id": "item.chain_rule.4", "chosen_is_key": False, "chosen_misconception_id": "misc.chain_rule_sum"},
        ],
        "expected_classification": {
            "class": "misconception_confirmed",
            "misconception_id": "misc.chain_rule_sum",
            "secondary_class": "missing_prerequisite",
            "root_skill": "skill.chain_rule",
        },
    },
    "expected_reflection_operators": ["INSERT_REMEDIATION", "DEFER", "ADD_PROBE"],
    "tutor_demo_questions": [
        "Why did my plan change?",
        "Why do I need the chain rule for PyTorch training?",
    ],
    "replay_mode_note": "record/replay LLM Gateway cache should be warmed for this scenario before a live "
                         "demo (design §38.3); DEMO_MODE=true seeds these files in one command.",
}


# --------------------------------------------------------------------------
# Writer
# --------------------------------------------------------------------------

def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "demo").mkdir(parents=True, exist_ok=True)

    write_json(OUT / "skills.json", SKILLS)
    write_json(OUT / "roles.json", ROLES)
    write_json(OUT / "skill_edges.json", SKILL_EDGES)
    write_json(OUT / "resources.json", RESOURCES)
    write_json(OUT / "misconceptions.json", MISCONCEPTIONS)
    write_json(OUT / "assessment_items.json", ITEMS)
    write_json(OUT / "demo" / "demo_learner.json", DEMO_LEARNER)
    (OUT / "demo" / "demo_resume.md").write_text(DEMO_RESUME_MD, encoding="utf-8")
    write_json(OUT / "demo" / "demo_learner_state.json", DEMO_LEARNER_STATE)
    write_json(OUT / "demo" / "demo_scenario.json", DEMO_SCENARIO)

    meta = {
        "graph_version": GRAPH_VERSION,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "counts": {
            "skills": len(SKILLS),
            "roles": len(ROLES),
            "skill_edges": len(SKILL_EDGES),
            "resources": len(RESOURCES),
            "misconceptions": len(MISCONCEPTIONS),
            "assessment_items": len(ITEMS),
        },
    }
    write_json(OUT / "meta.json", meta)

    print("Wrote dataset to", OUT)
    for k, v in meta["counts"].items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
