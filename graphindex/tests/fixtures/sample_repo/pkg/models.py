class Animal:
    def speak(self):
        return self.noise()
    def noise(self):
        return "..."

class Dog(Animal):
    def noise(self):
        return "woof"

class Cat(Animal):
    def noise(self):
        return "meow"
