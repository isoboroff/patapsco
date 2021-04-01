import argparse

from pipeline import Pipeline


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("config", help="Configuration file for the run")
    parser.add_argument("-v", dest="verbose", action="store_true", help="Increase verbosity of logger")
    args = parser.parse_args()

    pipeline = Pipeline(args.config, args.verbose)
    pipeline.run()
