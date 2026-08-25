#include <iostream>

class EngineBase {
public:
    virtual int base_speed() {
        return 100;
    }
};

class GameEngine : public EngineBase {
public:
    int step() {
        return 1;
    }

    int run() {
        return step();
    }
};
